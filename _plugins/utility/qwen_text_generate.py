from __future__ import annotations

import hashlib
import json
import os
import threading
import time
from typing import Any

import requests

from ..categories import LX_QWEN_CATEGORY


MODEL_LIST = ["qwen3.7-plus", "qwen3.6-flash", "qwen3.7-max"]
MODEL_ALIASES = {
    "均衡推荐（qwen3.7-plus）": "qwen3.7-plus",
    "快速省钱（qwen3.6-flash）": "qwen3.6-flash",
    "高质量（qwen3.7-max）": "qwen3.7-max",
}
DEFAULT_MODEL = "qwen3.7-plus"
STYLE_LIST = ["精准", "均衡", "创意"]
DEFAULT_STYLE = "均衡"
STYLE_SETTINGS = {
    "精准": {"temperature": 0.3, "top_p": 0.7},
    "均衡": {"temperature": 0.7, "top_p": 0.8},
    "创意": {"temperature": 1.0, "top_p": 0.9},
}
STYLE_ALIASES = {
    "precise": "精准",
    "balanced": "均衡",
    "creative": "创意",
}
DEFAULT_USER_PROMPT = ""
DEFAULT_SYSTEM_PROMPT = "你是专业文本助手。按用户要求处理文本，只输出可用结果，不添加无关内容。"
API_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"
PROGRESS_EVENT = "lx-qwen-text-progress"
CACHE_VERSION = 1
CACHE_DIR = os.path.join(os.path.dirname(os.path.realpath(__file__)), "qwen_text_cache")
CACHE_MAX_FILES = 256
CACHE_MAX_AGE_SECONDS = 30 * 24 * 60 * 60
CACHE_PRUNE_INTERVAL_SECONDS = 60 * 60
STREAM_EMIT_INTERVAL_SECONDS = 0.2
STREAM_EMIT_MIN_CHARS = 80
PROGRESS_TEXT_MAX_CHARS = 12000
_cache_lock = threading.RLock()
_cache_last_prune = 0.0


class QwenTextAPIError(RuntimeError):
    """Raised for API errors that should be shown directly to the user."""


def _log(message: str, level: str = "info") -> None:
    print(f"[LX][QwenText] {level}: {message}")


def _processing_interrupted() -> bool:
    try:
        import comfy.model_management

        return bool(comfy.model_management.processing_interrupted())
    except Exception:
        return False


def _raise_if_global_interrupted() -> None:
    try:
        import comfy.model_management

        comfy.model_management.throw_exception_if_processing_interrupted()
    except ImportError:
        return


def _is_global_interrupt_exception(exc: BaseException) -> bool:
    try:
        import comfy.model_management

        return isinstance(exc, comfy.model_management.InterruptProcessingException)
    except Exception:
        return False


def _start_interrupt_watcher(response: requests.Response) -> threading.Event:
    stop_event = threading.Event()

    def watch() -> None:
        while not stop_event.wait(0.1):
            if not _processing_interrupted():
                continue
            try:
                response.close()
            except Exception:
                pass
            return

    thread = threading.Thread(target=watch, name="LXQwenTextInterruptWatcher", daemon=True)
    thread.start()
    return stop_event


def _emit_progress(
    unique_id: Any,
    status: str,
    *,
    model: str = "",
    text: str = "",
    chars: int | None = None,
    elapsed: float | None = None,
    message: str = "",
    usage: Any = None,
) -> None:
    if unique_id in (None, ""):
        return

    payload: dict[str, Any] = {
        "node": str(unique_id),
        "status": status,
        "model": model,
        "text": text[-PROGRESS_TEXT_MAX_CHARS:] if text else "",
        "message": message,
    }
    if chars is not None:
        payload["chars"] = int(chars)
    if elapsed is not None:
        payload["elapsed"] = round(float(elapsed), 2)
    if isinstance(usage, dict):
        payload["usage"] = usage

    try:
        from server import PromptServer

        instance = getattr(PromptServer, "instance", None)
        if instance is None:
            return
        instance.send_sync(PROGRESS_EVENT, payload, getattr(instance, "client_id", None))
    except Exception:
        pass


def _looks_masked_api_key(value: str) -> bool:
    return "\u2022" in value or value.count("*") >= 4


def _resolve_api_key(api_key: str) -> str:
    value = (api_key or "").strip()
    if not value or value.lower() in ("none", "null"):
        return ""
    if _looks_masked_api_key(value):
        return ""
    return value


def _normalize_seed(seed: Any) -> int:
    try:
        value = int(float(seed))
    except (TypeError, ValueError):
        return 0
    if value < 0:
        value = abs(value)
    return value % 2147483647


def _resolve_model(model: str) -> str:
    value = str(model or "").strip()
    if value in MODEL_LIST:
        return value
    return MODEL_ALIASES.get(value, DEFAULT_MODEL)


def _resolve_style(style: str) -> str:
    value = str(style or "").strip()
    if value in STYLE_SETTINGS:
        return value
    return STYLE_ALIASES.get(value, DEFAULT_STYLE)


def _cache_path(cache_key: str) -> str:
    return os.path.join(CACHE_DIR, f"{cache_key}.json")


def _prune_cache_locked(force: bool = False) -> None:
    global _cache_last_prune

    now = time.time()
    if not force and now - _cache_last_prune < CACHE_PRUNE_INTERVAL_SECONDS:
        return
    _cache_last_prune = now

    if not os.path.isdir(CACHE_DIR):
        return

    entries: list[tuple[float, str]] = []
    for name in os.listdir(CACHE_DIR):
        path = os.path.join(CACHE_DIR, name)
        if not os.path.isfile(path):
            continue
        try:
            stat = os.stat(path)
        except OSError:
            continue

        if name.endswith(".tmp"):
            if now - stat.st_mtime > 24 * 60 * 60:
                try:
                    os.remove(path)
                except OSError as exc:
                    _log(f"cache temp cleanup failed: {exc}", "warning")
            continue

        if not name.endswith(".json"):
            continue

        if now - stat.st_mtime > CACHE_MAX_AGE_SECONDS:
            try:
                os.remove(path)
            except OSError as exc:
                _log(f"cache age cleanup failed: {exc}", "warning")
            continue

        entries.append((stat.st_mtime, path))

    for _, path in sorted(entries, reverse=True)[CACHE_MAX_FILES:]:
        try:
            os.remove(path)
        except OSError as exc:
            _log(f"cache size cleanup failed: {exc}", "warning")


def _read_cache(cache_key: str) -> str | None:
    path = _cache_path(cache_key)
    with _cache_lock:
        if not os.path.isfile(path):
            return None
        try:
            with open(path, "r", encoding="utf-8") as handle:
                payload = json.load(handle)
            if payload.get("version") != CACHE_VERSION:
                return None
            text = payload.get("text")
            return text if isinstance(text, str) else None
        except Exception as exc:
            _log(f"cache read failed: {exc}", "warning")
    return None


def _write_cache(cache_key: str, text: str, usage: Any) -> None:
    with _cache_lock:
        os.makedirs(CACHE_DIR, exist_ok=True)
        path = _cache_path(cache_key)
        tmp = f"{path}.tmp"
        payload = {
            "version": CACHE_VERSION,
            "created_at": int(time.time()),
            "text": text,
            "usage": usage if isinstance(usage, dict) else {},
        }
        with open(tmp, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        os.replace(tmp, path)
        _prune_cache_locked()


def _build_cache_key(
    model: str,
    style: str,
    user_prompt: str,
    system_prompt: str,
    seed: int,
) -> str:
    settings = STYLE_SETTINGS.get(style, STYLE_SETTINGS[DEFAULT_STYLE])
    payload = {
        "version": CACHE_VERSION,
        "api": "dashscope-openai-chat-completions",
        "model": model,
        "style": style,
        "temperature": settings["temperature"],
        "top_p": settings["top_p"],
        "user_prompt": user_prompt,
        "system_prompt": system_prompt,
        "seed": seed,
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _build_messages(user_prompt: str, system_prompt: str) -> list[dict[str, str]]:
    messages: list[dict[str, str]] = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": user_prompt})
    return messages


def _extract_text(data: dict[str, Any]) -> str:
    choices = data.get("choices")
    if not isinstance(choices, list) or not choices:
        raise ValueError("API response missing choices")
    message = choices[0].get("message", {}) if isinstance(choices[0], dict) else {}
    content = message.get("content")
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict):
                value = item.get("text") or item.get("content")
                if isinstance(value, str):
                    parts.append(value)
        return "\n".join(parts).strip()
    return ""


def _extract_stream_delta(data: dict[str, Any]) -> tuple[str, str | None]:
    choices = data.get("choices")
    if not isinstance(choices, list) or not choices:
        return "", None

    choice = choices[0] if isinstance(choices[0], dict) else {}
    delta = choice.get("delta", {})
    content = delta.get("content") if isinstance(delta, dict) else None

    if isinstance(content, str):
        text = content
    elif isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict):
                value = item.get("text") or item.get("content")
                if isinstance(value, str):
                    parts.append(value)
        text = "".join(parts)
    else:
        text = ""

    finish_reason = choice.get("finish_reason")
    return text, finish_reason if isinstance(finish_reason, str) else None


def _iter_sse_payloads(response: requests.Response):
    for raw_line in response.iter_lines(decode_unicode=True):
        if not raw_line:
            continue
        line = raw_line.decode("utf-8", "replace") if isinstance(raw_line, bytes) else str(raw_line)
        line = line.strip()
        if not line or line.startswith(":"):
            continue
        if line.startswith("data:"):
            line = line[5:].strip()
        if not line:
            continue
        if line == "[DONE]":
            break
        yield json.loads(line)


def _stream_completion(
    payload: dict[str, Any],
    headers: dict[str, str],
    unique_id: Any,
    model: str,
) -> tuple[str, Any]:
    started = time.time()
    response: requests.Response | None = None
    watcher_stop: threading.Event | None = None
    chunks: list[str] = []
    usage: Any = {}
    last_emit = 0.0
    last_emit_chars = 0

    try:
        _raise_if_global_interrupted()
        response = requests.post(
            API_URL,
            headers=headers,
            json=payload,
            stream=True,
            timeout=(10, 180),
        )
        watcher_stop = _start_interrupt_watcher(response)
        _raise_if_global_interrupted()

        if response.status_code >= 400:
            try:
                err: Any = response.json()
            except Exception:
                err = response.text[:500]
            raise QwenTextAPIError(f"Qwen 文本生成 API 调用失败 HTTP {response.status_code}: {err}")

        _emit_progress(
            unique_id,
            "connected",
            model=model,
            chars=0,
            elapsed=time.time() - started,
            message="已连接，等待首段文本",
        )

        for data in _iter_sse_payloads(response):
            _raise_if_global_interrupted()

            if isinstance(data.get("usage"), dict):
                usage = data["usage"]

            delta, finish_reason = _extract_stream_delta(data)
            if delta:
                chunks.append(delta)

            text = "".join(chunks)
            now = time.time()
            should_emit = (
                delta
                and (
                    now - last_emit >= STREAM_EMIT_INTERVAL_SECONDS
                    or len(text) - last_emit_chars >= STREAM_EMIT_MIN_CHARS
                )
            )
            if should_emit:
                _emit_progress(
                    unique_id,
                    "streaming",
                    model=model,
                    text=text,
                    chars=len(text),
                    elapsed=now - started,
                    message="正在生成文本...",
                )
                last_emit = now
                last_emit_chars = len(text)

            if finish_reason:
                break

        _raise_if_global_interrupted()
        result = "".join(chunks).strip()
        if not result:
            raise QwenTextAPIError("Qwen 文本生成 API 未返回文本内容。")

        _emit_progress(
            unique_id,
            "done",
            model=model,
            text=result,
            chars=len(result),
            elapsed=time.time() - started,
            message="生成完成",
            usage=usage,
        )
        return result, usage
    except requests.RequestException:
        if _processing_interrupted():
            text = "".join(chunks).strip()
            _emit_progress(
                unique_id,
                "cancelled",
                model=model,
                text=text,
                chars=len(text),
                elapsed=time.time() - started,
                message="已取消",
            )
        _raise_if_global_interrupted()
        raise
    except BaseException as exc:
        if _is_global_interrupt_exception(exc):
            text = "".join(chunks).strip()
            _emit_progress(
                unique_id,
                "cancelled",
                model=model,
                text=text,
                chars=len(text),
                elapsed=time.time() - started,
                message="已取消",
            )
        raise
    finally:
        if watcher_stop is not None:
            watcher_stop.set()
        if response is not None:
            response.close()


def _summarize_usage(usage: Any) -> str:
    if not isinstance(usage, dict):
        return ""
    keys = ("prompt_tokens", "completion_tokens", "total_tokens", "input_tokens", "output_tokens")
    parts = [f"{key}={usage[key]}" for key in keys if key in usage]
    return ", ".join(parts)


class LXQwenTextGenerate:
    """Generate or transform text through Qwen text models."""

    CATEGORY = LX_QWEN_CATEGORY
    SEARCH_ALIASES = [
        "lx",
        "LX",
        "灵犀",
        "Qwen3 文本生成",
        "Qwen 文本生成",
        "Qwen Text Generate",
        "文本生成",
        "文本处理",
        "文本改写",
        "提示词生成",
        "qwen",
    ]
    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("text",)
    FUNCTION = "generate"

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "model": (
                    MODEL_LIST,
                    {
                        "default": DEFAULT_MODEL,
                        "tooltip": (
                            "qwen3.7-plus：默认推荐，质量/速度/成本均衡。\n"
                            "qwen3.6-flash：速度优先，适合批量文本处理。\n"
                            "qwen3.7-max：质量优先，适合复杂文本和高要求任务。"
                        ),
                    },
                ),
                "user_prompt": ("STRING", {"default": DEFAULT_USER_PROMPT, "multiline": True}),
                "system_prompt": ("STRING", {"default": DEFAULT_SYSTEM_PROMPT, "multiline": True}),
                "creativity": (
                    STYLE_LIST,
                    {
                        "default": DEFAULT_STYLE,
                        "tooltip": (
                            "精准：更稳定克制，适合翻译、总结和严格改写。\n"
                            "均衡：默认推荐，适合大多数文本生成和改写。\n"
                            "创意：更发散，适合标题、文案和灵感扩展。"
                        ),
                    },
                ),
                "seed": (
                    "INT",
                    {
                        "default": 0,
                        "min": 0,
                        "max": 0xffffffffffffffff,
                        "control_after_generate": True,
                    },
                ),
                "api_key": ("STRING", {"default": "", "multiline": False}),
            },
            "hidden": {
                "unique_id": "UNIQUE_ID",
            },
        }

    def generate(
        self,
        model: str,
        user_prompt: str,
        system_prompt: str,
        creativity: str,
        seed: int,
        api_key: str,
        unique_id=None,
    ):
        api_key = _resolve_api_key(api_key)
        if not api_key:
            message = "错误：api_key 为必填项，请填写阿里云百炼 API Key。"
            return (message,)

        model = _resolve_model(model)
        style = _resolve_style(creativity)
        user_prompt = str(user_prompt or "").strip()
        system_prompt = str(system_prompt or "").strip()
        if not user_prompt:
            message = "错误：user_prompt 不能为空。"
            return (message,)

        seed_value = _normalize_seed(seed)
        cache_key = _build_cache_key(model, style, user_prompt, system_prompt, seed_value)
        cached = _read_cache(cache_key)
        if cached is not None:
            _log(f"cache hit: {cache_key[:12]}")
            _emit_progress(
                unique_id,
                "cache",
                model=model,
                text=cached,
                chars=len(cached),
                elapsed=0,
                message="命中缓存",
            )
            return (cached,)

        settings = STYLE_SETTINGS[style]
        payload = {
            "model": model,
            "messages": _build_messages(user_prompt, system_prompt),
            "temperature": settings["temperature"],
            "top_p": settings["top_p"],
            "seed": seed_value,
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

        try:
            _emit_progress(unique_id, "start", model=model, chars=0, elapsed=0, message="正在连接 Qwen API...")
            result_text, usage = _stream_completion(payload, headers, unique_id, model)
            usage_text = _summarize_usage(usage)
            if usage_text:
                _log(f"{model} usage: {usage_text}")
            _write_cache(cache_key, result_text, usage)
            return (result_text,)
        except QwenTextAPIError as exc:
            message = f"错误：{exc}"
            _emit_progress(unique_id, "error", model=model, message=message)
            return (message,)
        except requests.RequestException as exc:
            message = f"错误：Qwen 文本生成 API 网络请求失败：{exc}"
            _emit_progress(unique_id, "error", model=model, message=message)
            return (message,)
        except Exception as exc:
            message = f"错误：Qwen 文本生成 API 响应解析失败：{exc}"
            _emit_progress(unique_id, "error", model=model, message=message)
            return (message,)
