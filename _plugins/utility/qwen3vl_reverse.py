from __future__ import annotations

import base64
import hashlib
import json
import os
import threading
import time
from io import BytesIO
from typing import Any

import numpy as np
import requests
import torch
from PIL import Image

from ..categories import LX_QWEN_CATEGORY


MODEL_LIST = ["qwen3-vl-flash", "qwen3-vl-plus"]
DEFAULT_MODEL = "qwen3-vl-plus"
DEFAULT_PROMPT = "请描述这张图片"
API_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"
MAX_IMAGES = 4
MAX_IMAGE_EDGE = 2048
MAX_IMAGE_BYTES = 6 * 1024 * 1024
CACHE_VERSION = 1
CACHE_DIR = os.path.join(os.path.dirname(os.path.realpath(__file__)), "qwen3vl_cache")
CACHE_MAX_FILES = 256
CACHE_MAX_AGE_SECONDS = 30 * 24 * 60 * 60
CACHE_PRUNE_INTERVAL_SECONDS = 60 * 60
_cache_lock = threading.RLock()
_cache_last_prune = 0.0


def _log(message: str, level: str = "info") -> None:
    prefix = "[LX][Qwen3VL]"
    print(f"{prefix} {level}: {message}")


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


def _tensor_to_pil(image: torch.Tensor) -> Image.Image:
    data = image.detach().cpu()
    if data.ndim == 4:
        data = data[0]
    if data.ndim != 3:
        raise ValueError(f"Unsupported image tensor shape: {tuple(data.shape)}")

    if data.shape[-1] in (1, 3, 4):
        arr = data.numpy()
    elif data.shape[0] in (1, 3, 4):
        arr = data.permute(1, 2, 0).numpy()
    else:
        raise ValueError(f"Unsupported image tensor shape: {tuple(data.shape)}")

    if arr.shape[-1] == 1:
        arr = np.repeat(arr, 3, axis=-1)
    elif arr.shape[-1] == 4:
        arr = arr[..., :3]

    arr = np.nan_to_num(arr.astype(np.float32), nan=0.0, posinf=1.0, neginf=0.0)
    if arr.size and float(np.max(arr)) > 1.0 + 1e-3:
        arr = arr / 255.0
    arr = (np.clip(arr, 0.0, 1.0) * 255.0).astype(np.uint8)
    return Image.fromarray(arr, mode="RGB")


def _resize_for_api(img: Image.Image) -> Image.Image:
    width, height = img.size
    longest = max(width, height)
    if longest <= MAX_IMAGE_EDGE:
        return img
    scale = MAX_IMAGE_EDGE / float(longest)
    size = (max(1, round(width * scale)), max(1, round(height * scale)))
    return img.resize(size, Image.Resampling.LANCZOS)


def _encode_image(image: torch.Tensor) -> tuple[str, str, dict[str, int]]:
    img = _resize_for_api(_tensor_to_pil(image).convert("RGB"))
    quality = 90
    encoded = b""

    for _ in range(6):
        buffer = BytesIO()
        img.save(buffer, format="JPEG", quality=quality, optimize=True)
        encoded = buffer.getvalue()
        if len(encoded) <= MAX_IMAGE_BYTES:
            break
        if quality > 65:
            quality -= 10
        else:
            width, height = img.size
            img = img.resize(
                (max(1, int(width * 0.82)), max(1, int(height * 0.82))),
                Image.Resampling.LANCZOS,
            )

    digest = hashlib.sha256(encoded).hexdigest()
    uri = "data:image/jpeg;base64," + base64.b64encode(encoded).decode("ascii")
    meta = {"width": img.size[0], "height": img.size[1], "bytes": len(encoded)}
    return uri, digest, meta


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


def _build_cache_key(model: str, prompt: str, seed: int, image_hashes: list[str]) -> str:
    payload = {
        "version": CACHE_VERSION,
        "api": "dashscope-openai-chat-completions",
        "model": model,
        "prompt": prompt,
        "seed": seed,
        "image_hashes": image_hashes,
        "max_image_edge": MAX_IMAGE_EDGE,
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _image_alias_line(index: int) -> str:
    cn_nums = ["一", "二", "三", "四"]
    cn = cn_nums[index - 1]
    return (
        f"【图{index} / 图{cn} / image{index} / 第{cn}张】"
        f"下面这张图片是第 {index} 张参考图。"
    )


def _build_messages(prompt: str, image_uris: list[str]) -> list[dict[str, Any]]:
    content: list[dict[str, Any]] = [
        {
            "type": "text",
            "text": (
                "你将收到 1 到 4 张图片。用户可能用 图1、图一、第一张、image1 "
                "指代第 1 张图片；图2、图二、第二张、image2 指代第 2 张图片，"
                "以此类推。请严格按用户要求理解这些引用，只输出最终文本。"
            ),
        }
    ]
    for index, uri in enumerate(image_uris, start=1):
        content.append({"type": "text", "text": _image_alias_line(index)})
        content.append({"type": "image_url", "image_url": {"url": uri}})
    content.append({"type": "text", "text": f"用户要求：\n{prompt}"})
    return [{"role": "user", "content": content}]


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


def _summarize_usage(usage: Any) -> str:
    if not isinstance(usage, dict):
        return ""
    keys = ("prompt_tokens", "completion_tokens", "total_tokens", "input_tokens", "output_tokens", "image_tokens")
    parts = [f"{key}={usage[key]}" for key in keys if key in usage]
    return ", ".join(parts)


class LXQwen3VLReverse:
    """Reverse prompt text from one or more images through Qwen3-VL."""

    CATEGORY = LX_QWEN_CATEGORY
    SEARCH_ALIASES = ["lx", "LX", "灵犀", "Qwen3VL 图像反推", "图像反推", "反推提示词", "qwen3vl"]
    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("text",)
    FUNCTION = "reverse"

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "image1": ("IMAGE",),
                "model": (
                    MODEL_LIST,
                    {
                        "default": DEFAULT_MODEL,
                        "tooltip": (
                            "默认选 Plus；批量、省钱或快速预览时选 Flash。\n"
                            "qwen3-vl-flash：速度优先，更快更便宜，适合批量处理和日常描述。\n"
                            "qwen3-vl-plus：默认推荐，细节更稳，适合图像反推、复杂画面和文字关系。"
                        ),
                    },
                ),
                "prompt": ("STRING", {"default": DEFAULT_PROMPT, "multiline": True}),
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
            "optional": {
                "image2": ("IMAGE",),
                "image3": ("IMAGE",),
                "image4": ("IMAGE",),
            },
        }

    def reverse(
        self,
        image1: torch.Tensor,
        model: str,
        prompt: str,
        seed: int,
        api_key: str,
        image2: torch.Tensor | None = None,
        image3: torch.Tensor | None = None,
        image4: torch.Tensor | None = None,
    ):
        api_key = _resolve_api_key(api_key)
        if not api_key:
            return ("错误：api_key 为必填项，请填写阿里云百炼 API Key。",)

        model = model if model in MODEL_LIST else DEFAULT_MODEL
        prompt = str(prompt or "").strip() or DEFAULT_PROMPT
        seed_value = _normalize_seed(seed)
        tensors = [item for item in (image1, image2, image3, image4) if item is not None]

        try:
            encoded_images = [_encode_image(item) for item in tensors[:MAX_IMAGES]]
        except Exception as exc:
            return (f"错误：图片编码失败：{exc}",)

        image_uris = [item[0] for item in encoded_images]
        image_hashes = [item[1] for item in encoded_images]
        cache_key = _build_cache_key(model, prompt, seed_value, image_hashes)
        cached = _read_cache(cache_key)
        if cached is not None:
            _log(f"cache hit: {cache_key[:12]}")
            return (cached,)

        payload = {
            "model": model,
            "messages": _build_messages(prompt, image_uris),
            "seed": seed_value,
        }
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

        try:
            response = requests.post(API_URL, headers=headers, json=payload, timeout=180)
            if response.status_code >= 400:
                try:
                    err = response.json()
                except Exception:
                    err = response.text[:500]
                return (f"错误：Qwen3VL API 调用失败 HTTP {response.status_code}: {err}",)
            data = response.json()
            text = _extract_text(data)
            if not text:
                return ("错误：Qwen3VL API 未返回文本内容。",)
            usage = data.get("usage", {})
            usage_text = _summarize_usage(usage)
            if usage_text:
                _log(f"{model} usage: {usage_text}")
            _write_cache(cache_key, text, usage)
            return (text,)
        except requests.RequestException as exc:
            return (f"错误：Qwen3VL API 网络请求失败：{exc}",)
        except Exception as exc:
            return (f"错误：Qwen3VL API 响应解析失败：{exc}",)
