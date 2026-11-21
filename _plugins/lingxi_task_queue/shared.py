# -*- coding: utf-8 -*-
from __future__ import annotations

import hashlib
import json
import os
import threading
import time
from dataclasses import dataclass
from typing import Any

import torch
from PIL import Image, ImageDraw, ImageFont

from ..lingxi_bridge.lb_cache_paths import get_cache_dir
from ..lingxi_bridge.lb_utils import pil2tensor


TASKS_TYPE = "LX_IMAGE_TASKS"
RESULTS_TYPE = "LX_IMAGE_RESULTS"
MAX_TASKS = 32
MAX_TASK_IMAGES = 8
DEFAULT_SPLIT_COUNT = 8
EMPTY_SIZE = (512, 512)
DEFAULT_PLACEHOLDER_SIZE = (1024, 1024)
CACHE_DIR = get_cache_dir("task_queue")
CACHE_MAX_MB_ENV = "LX_TASK_QUEUE_CACHE_MAX_MB"
CACHE_MAX_DAYS_ENV = "LX_TASK_QUEUE_CACHE_MAX_DAYS"
DEFAULT_CACHE_MAX_MB = 512
DEFAULT_CACHE_MAX_DAYS = 7
CACHE_CLEANUP_INTERVAL_SECONDS = 300
LONG_IMAGE_MAX_PIXELS = 32_000_000

_cache_cleanup_lock = threading.Lock()
_last_cache_cleanup = 0.0


@dataclass(frozen=True)
class Channel:
    source: str
    api_index: int
    platform: str
    api_base: str
    api_format: str
    model: str
    api_key: str
    origin_label: str = ""

    def to_info_json(self) -> str:
        return json.dumps(
            {
                "apikey": self.api_key,
                "api_base": self.api_base,
                "model": self.model,
                "platform": self.platform,
                "api_format": self.api_format,
            },
            ensure_ascii=False,
        )

    def key_hash(self) -> str:
        return hash_text(self.api_key)

    def key_identity(self) -> str:
        return sha_json(
            {
                "source": self.source,
                "api_index": self.api_index,
                "api_key_hash": self.key_hash(),
                "platform": self.platform,
                "api_base": self.api_base,
                "api_format": self.api_format,
                "model": self.model,
            }
        )

    def origin(self) -> str:
        return self.origin_label or self.source or f"key {self.api_index}"

    def display_label(self) -> str:
        return f"Key #{self.api_index} / {self.origin()} / hash {self.key_hash()[:8]}"

    def semantic_fingerprint(self) -> dict[str, Any]:
        return {
            "platform": self.platform,
            "api_base": self.api_base,
            "api_format": self.api_format,
            "model": self.model,
        }

    def semantic_identity(self) -> str:
        return sha_json(self.semantic_fingerprint())

    def fingerprint(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "api_index": self.api_index,
            "origin_label": self.origin(),
            "platform": self.platform,
            "api_base": self.api_base,
            "api_format": self.api_format,
            "model": self.model,
            "api_key_hash": self.key_hash(),
        }

    def public_status(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "api_index": self.api_index,
            "origin_label": self.origin(),
            "platform": self.platform,
            "api_base": self.api_base,
            "api_format": self.api_format,
            "model": self.model,
            "api_key_hash": self.key_hash(),
        }


def clean_str(value: object) -> str:
    return "" if value is None else str(value).strip()


def clip(value: object, limit: int = 500) -> str:
    text = "" if value is None else str(value)
    return text if len(text) <= limit else text[:limit] + "..."


def hash_text(value: object) -> str:
    text = "" if value is None else str(value)
    return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()[:16]


def sha_json(data: object) -> str:
    raw = json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8", errors="replace")).hexdigest()


def safe_json_loads(value: object) -> dict[str, Any]:
    if not isinstance(value, str) or not value.strip():
        return {}
    try:
        data = json.loads(value)
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def tensor_hash(tensor: torch.Tensor) -> str:
    t = tensor.detach().cpu().contiguous()
    arr = t.numpy()
    digest = hashlib.sha256()
    digest.update(str(tuple(arr.shape)).encode("ascii", errors="ignore"))
    digest.update(arr.tobytes())
    return digest.hexdigest()


def image_group_hash(images: list[torch.Tensor]) -> str:
    payload = []
    for index, image in enumerate(images, start=1):
        payload.append({"index": index, "hash": tensor_hash(image)})
    return sha_json(payload)


def normalize_tasks(value: object) -> list[dict[str, Any]]:
    if isinstance(value, dict) and value.get("type") == "lx_image_tasks":
        raw = value.get("tasks", [])
    elif isinstance(value, list):
        raw = value
    else:
        raw = []
    return [item for item in raw if isinstance(item, dict)]


def task_payload(tasks: list[dict[str, Any]]) -> dict[str, Any]:
    return {"type": "lx_image_tasks", "version": 1, "tasks": tasks[:MAX_TASKS]}


def parse_api_channels(value: object, fallback_source: str = "api") -> list[Channel]:
    data = safe_json_loads(value)
    if not data:
        return []

    if data.get("type") == "lingxi_api_pool":
        raw_channels = data.get("channels")
        if isinstance(raw_channels, list):
            channels: list[Channel] = []
            for index, item in enumerate(raw_channels, start=1):
                if not isinstance(item, dict):
                    continue
                api_key = clean_str(item.get("api_key") or item.get("apikey"))
                if not api_key or api_key.lower() in {"none", "null"}:
                    continue
                try:
                    api_index = int(item.get("api_index") or index)
                except (TypeError, ValueError):
                    api_index = index
                channels.append(
                    Channel(
                        source=clean_str(item.get("source") or fallback_source),
                        api_index=api_index,
                        platform=clean_str(item.get("platform") or "banana-pro"),
                        api_base=clean_str(item.get("api_base")).rstrip("/"),
                        api_format=clean_str(item.get("api_format") or "v1/images"),
                        model=clean_str(item.get("model")),
                        api_key=api_key,
                        origin_label=clean_str(item.get("origin_label") or item.get("origin") or ""),
                    )
                )
            return channels

        platform = clean_str(data.get("platform") or "banana-pro")
        api_base = clean_str(data.get("api_base")).rstrip("/")
        api_format = clean_str(data.get("api_format") or "v1/images")
        model = clean_str(data.get("model"))
        keys = data.get("api_keys") or []
        if not isinstance(keys, list):
            return []
        channels = []
        for index, key in enumerate(keys, start=1):
            api_key = clean_str(key)
            if not api_key or api_key.lower() in {"none", "null"}:
                continue
            channels.append(
                Channel(
                    source=fallback_source,
                    api_index=index,
                    platform=platform,
                    api_base=api_base,
                    api_format=api_format,
                    model=model,
                    api_key=api_key,
                    origin_label=f"{fallback_source} key {index}",
                )
            )
        return channels

    api_key = clean_str(data.get("apikey") or data.get("api_key"))
    api_base = clean_str(data.get("api_base")).rstrip("/")
    api_format = clean_str(data.get("api_format") or "v1/images")
    model = clean_str(data.get("model"))
    platform = clean_str(data.get("platform") or "banana-pro")
    if not any([api_key, api_base, api_format, model, platform]):
        return []
    return [
        Channel(
            source=fallback_source,
            api_index=1,
            platform=platform,
            api_base=api_base,
            api_format=api_format,
            model=model,
            api_key=api_key,
            origin_label=fallback_source,
        )
    ]


def channel_source_key(api_value: object) -> str:
    data = safe_json_loads(api_value)
    return sha_json(data) if data else hash_text(api_value)


def parse_response_json(value: object) -> dict[str, Any]:
    data = safe_json_loads(value)
    return data if data else {}


KEY_FATAL_ERROR_CODES = {"HTTP_401", "HTTP_403", "HTTP_402", "API_KEY", "QUOTA"}
KEY_TRANSIENT_ERROR_CODES = {"HTTP_429", "RATE_LIMIT", "CONCURRENT_LIMIT", "TIMEOUT"}
TASK_ERROR_CODES = {"CONTENT_POLICY"}


def response_message(data: dict[str, Any], fallback: object = "") -> str:
    error = data.get("error")
    if isinstance(error, dict):
        for key in ("message", "error", "detail", "reason"):
            value = error.get(key)
            if value:
                return str(value)
    for key in ("message", "error", "detail", "reason"):
        value = data.get(key)
        if value:
            return str(value)
    return "" if fallback is None else str(fallback)


def is_key_fatal_error(code: object, reason: object = "") -> bool:
    code_text = "" if code is None else str(code)
    if code_text in KEY_FATAL_ERROR_CODES:
        return True
    lower = str(reason or "").lower()
    return any(
        token in lower
        for token in (
            "api key",
            "apikey",
            "authorization",
            "unauthorized",
            "forbidden",
            "invalid token",
            "invalid credential",
            "permission",
            "billing",
            "balance",
            "quota",
            "credit",
            "insufficient",
            "令牌",
            "权限",
            "授权",
            "欠费",
            "余额",
            "额度",
        )
    )


def is_key_transient_error(code: object, reason: object = "") -> bool:
    code_text = "" if code is None else str(code)
    if code_text in KEY_TRANSIENT_ERROR_CODES:
        return True
    lower = str(reason or "").lower()
    return any(
        token in lower
        for token in (
            "rate limit",
            "too many requests",
            "concurrent",
            "another request",
            "only one request",
            "timeout",
            "timed out",
            "限流",
            "并发",
            "超时",
        )
    )


def should_failover_key(code: object, reason: object = "") -> bool:
    return is_key_fatal_error(code, reason) or is_key_transient_error(code, reason)


def classify_error(response: object, explanation: object = "") -> tuple[str, str]:
    data = parse_response_json(response)
    error = data.get("error")
    status = data.get("status")
    error_type = ""
    if isinstance(error, dict):
        status = status or error.get("status")
        error_type = clean_str(error.get("type") or error.get("code"))
    message = response_message(data, explanation or response)
    msg = clip(message, 800)
    lower = f"{msg} {error_type}".lower()
    if any(token in lower for token in ("api key", "apikey", "authorization", "unauthorized", "forbidden", "invalid token", "invalid credential", "令牌", "权限", "授权")):
        code = "API_KEY"
    elif any(token in lower for token in ("balance", "quota", "credit", "billing", "insufficient", "欠费", "余额", "额度")):
        code = "QUOTA"
    elif any(token in lower for token in ("policy", "moderation", "safety", "sensitive", "unsafe", "安全", "敏感", "违规")):
        code = "CONTENT_POLICY"
    elif "429" in lower or "rate limit" in lower or "too many requests" in lower:
        code = "RATE_LIMIT"
    elif "concurrent" in lower or "another request" in lower or "only one request" in lower:
        code = "CONCURRENT_LIMIT"
    elif "timeout" in lower or "timed out" in lower:
        code = "TIMEOUT"
    elif status:
        code = f"HTTP_{status}"
    else:
        code = "ERROR"
    return code, msg


def friendly_error(code: object, reason: object = "") -> str:
    code_text = "" if code is None else str(code)
    reason_text = clip(reason, 180)
    status_map = {
        "HTTP_401": "API Key 无效或无权限",
        "HTTP_403": "API Key 无效或无权限",
        "HTTP_402": "接口返回付款/额度类拒绝",
        "HTTP_429": "限流或并发限制",
        "RATE_LIMIT": "限流或并发限制",
        "CONCURRENT_LIMIT": "疑似当前 API 不支持并发",
        "TIMEOUT": "请求超时",
        "QUOTA": "接口返回余额/额度类拒绝；若后台余额正常，通常与高并发预扣、账户池或上游路由限制有关",
        "CONTENT_POLICY": "内容安全策略拦截",
        "API_KEY": "API Key 无效或未填写",
        "NO_API": "没有可用 API 配置",
        "NO_HEALTHY_API_KEY": "没有可用的健康 API Key",
        "ERROR": "生成失败",
        "UNKNOWN": "未知错误",
    }
    friendly = status_map.get(code_text)
    if not friendly and code_text.startswith("HTTP_"):
        friendly = f"接口返回 {code_text.replace('HTTP_', 'HTTP ')}"
    if not friendly:
        friendly = code_text or "生成失败"
    if reason_text and reason_text != friendly:
        return f"{friendly}，{reason_text}"
    return friendly


def make_placeholder(size: tuple[int, int], title: str, detail: str = "", fill=(48, 48, 48)) -> Image.Image:
    width, height = max(64, int(size[0])), max(64, int(size[1]))
    image = Image.new("RGB", (width, height), fill)
    draw = ImageDraw.Draw(image)
    try:
        font = ImageFont.truetype("arial.ttf", max(16, min(width, height) // 24))
        small = ImageFont.truetype("arial.ttf", max(12, min(width, height) // 34))
    except Exception:
        font = ImageFont.load_default()
        small = font
    lines = [title]
    if detail:
        lines.append(clip(detail, 90))
    line_heights = []
    total_h = 0
    for idx, line in enumerate(lines):
        f = font if idx == 0 else small
        bbox = draw.textbbox((0, 0), line, font=f)
        h = bbox[3] - bbox[1]
        line_heights.append(h)
        total_h += h + 8
    y = max(12, (height - total_h) // 2)
    for idx, line in enumerate(lines):
        f = font if idx == 0 else small
        bbox = draw.textbbox((0, 0), line, font=f)
        w = bbox[2] - bbox[0]
        x = max(12, (width - w) // 2)
        draw.text((x, y), line, fill=(235, 235, 235), font=f)
        y += line_heights[idx] + 8
    return image


def blank_image(size: tuple[int, int] = EMPTY_SIZE) -> Image.Image:
    return Image.new("RGB", size, (255, 255, 255))


def to_tensor(image: Image.Image) -> torch.Tensor:
    return pil2tensor(image.convert("RGB"))


def batch_tensor(images: list[Image.Image], fallback_size: tuple[int, int] = EMPTY_SIZE) -> torch.Tensor:
    if not images:
        return to_tensor(blank_image(fallback_size))
    width = max(max(1, image.width) for image in images)
    height = max(max(1, image.height) for image in images)
    tensors = []
    for image in images:
        normalized = image.convert("RGB")
        canvas = Image.new("RGB", (width, height), (255, 255, 255))
        x = max(0, (width - normalized.width) // 2)
        y = max(0, (height - normalized.height) // 2)
        canvas.paste(normalized, (x, y))
        tensors.append(to_tensor(canvas))
    return torch.cat(tensors, dim=0)


def long_image(images: list[Image.Image], fallback_size: tuple[int, int] = EMPTY_SIZE) -> tuple[Image.Image, bool]:
    if not images:
        return blank_image(fallback_size), False
    width = images[0].width
    normalized = []
    for image in images:
        current = image.convert("RGB")
        if current.width != width:
            ratio = width / max(1, current.width)
            height = max(1, int(round(current.height * ratio)))
            current = current.resize((width, height), Image.LANCZOS)
        normalized.append(current)
    total_height = sum(image.height for image in normalized)
    scaled = False
    if width * total_height > LONG_IMAGE_MAX_PIXELS:
        scale = (LONG_IMAGE_MAX_PIXELS / max(1, width * total_height)) ** 0.5
        width = max(1, int(width * scale))
        next_images = []
        for image in normalized:
            height = max(1, int(image.height * scale))
            next_images.append(image.resize((width, height), Image.LANCZOS))
        normalized = next_images
        total_height = sum(image.height for image in normalized)
        scaled = True
    canvas = Image.new("RGB", (width, total_height), (255, 255, 255))
    y = 0
    for image in normalized:
        canvas.paste(image, (0, y))
        y += image.height
    return canvas, scaled


def first_image_size(images: list[Image.Image]) -> tuple[int, int]:
    for image in images:
        if isinstance(image, Image.Image):
            return image.size
    return DEFAULT_PLACEHOLDER_SIZE


def cache_root(unique_id: object) -> str:
    node_id = clean_str(unique_id) or "default"
    node_id = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in node_id)
    return os.path.join(CACHE_DIR, node_id)


def cache_paths(unique_id: object, input_hash: str) -> tuple[str, str]:
    root = cache_root(unique_id)
    os.makedirs(root, exist_ok=True)
    base = os.path.join(root, input_hash[:32])
    return base + ".png", base + ".json"


def load_cached_image(unique_id: object, input_hash: str) -> tuple[Image.Image | None, dict[str, Any]]:
    image_path, meta_path = cache_paths(unique_id, input_hash)
    if not os.path.isfile(image_path):
        return None, {}
    try:
        image = Image.open(image_path).convert("RGB")
    except Exception:
        return None, {}
    meta: dict[str, Any] = {}
    if os.path.isfile(meta_path):
        try:
            with open(meta_path, "r", encoding="utf-8") as f:
                raw = json.load(f)
            if isinstance(raw, dict):
                meta = raw
        except Exception:
            meta = {}
    touch_cache_files(image_path, meta_path)
    return image, meta


def save_cached_image(unique_id: object, input_hash: str, image: Image.Image, meta: dict[str, Any]) -> None:
    image_path, meta_path = cache_paths(unique_id, input_hash)
    image.save(image_path, format="PNG")
    safe_meta = dict(meta)
    safe_meta.pop("api_key", None)
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(safe_meta, f, ensure_ascii=False, indent=2)
        f.write("\n")
    cleanup_cache()


def env_int(name: str, default: int) -> int:
    raw = os.environ.get(name, "")
    if not raw.strip():
        return default
    try:
        return max(0, int(float(raw)))
    except (TypeError, ValueError):
        return default


def cache_max_bytes() -> int:
    return env_int(CACHE_MAX_MB_ENV, DEFAULT_CACHE_MAX_MB) * 1024 * 1024


def cache_max_age_seconds() -> int:
    return env_int(CACHE_MAX_DAYS_ENV, DEFAULT_CACHE_MAX_DAYS) * 24 * 60 * 60


def safe_file_size(path: str) -> int:
    try:
        return os.path.getsize(path) if os.path.isfile(path) else 0
    except OSError:
        return 0


def touch_cache_files(*paths: str) -> None:
    now = time.time()
    for path in paths:
        try:
            if path and os.path.exists(path):
                os.utime(path, (now, now))
        except OSError:
            pass


def remove_file(path: str) -> None:
    try:
        if path and os.path.isfile(path):
            os.remove(path)
    except OSError:
        pass


def cache_records() -> list[dict[str, Any]]:
    if not os.path.isdir(CACHE_DIR):
        return []
    records: list[dict[str, Any]] = []
    for current, dirs, files in os.walk(CACHE_DIR):
        dirs[:] = [name for name in dirs if not name.startswith(".")]
        for name in files:
            if not name.lower().endswith(".png"):
                continue
            image_path = os.path.join(current, name)
            try:
                stat = os.stat(image_path)
            except OSError:
                continue
            meta_path = os.path.splitext(image_path)[0] + ".json"
            records.append(
                {
                    "image_path": image_path,
                    "meta_path": meta_path,
                    "size": int(stat.st_size) + safe_file_size(meta_path),
                    "mtime": float(stat.st_mtime),
                }
            )
    return records


def remove_cache_record(record: dict[str, Any]) -> None:
    remove_file(str(record.get("image_path") or ""))
    remove_file(str(record.get("meta_path") or ""))


def cleanup_orphan_cache_metadata() -> None:
    if not os.path.isdir(CACHE_DIR):
        return
    for current, _dirs, files in os.walk(CACHE_DIR):
        for name in files:
            if not name.lower().endswith(".json"):
                continue
            meta_path = os.path.join(current, name)
            image_path = os.path.splitext(meta_path)[0] + ".png"
            if not os.path.isfile(image_path):
                remove_file(meta_path)


def cleanup_cache(force: bool = False) -> None:
    global _last_cache_cleanup
    now = time.time()
    if not force and now - _last_cache_cleanup < CACHE_CLEANUP_INTERVAL_SECONDS:
        return
    if not _cache_cleanup_lock.acquire(blocking=False):
        return
    try:
        now = time.time()
        if not force and now - _last_cache_cleanup < CACHE_CLEANUP_INTERVAL_SECONDS:
            return
        _last_cache_cleanup = now

        records = cache_records()
        if not records:
            cleanup_orphan_cache_metadata()
            return

        max_age = cache_max_age_seconds()
        if max_age > 0:
            cutoff = now - max_age
            kept: list[dict[str, Any]] = []
            for record in records:
                if float(record.get("mtime", 0.0)) < cutoff:
                    remove_cache_record(record)
                else:
                    kept.append(record)
            records = kept

        max_bytes = cache_max_bytes()
        if max_bytes > 0:
            total = sum(int(record.get("size", 0)) for record in records)
            if total > max_bytes:
                for record in sorted(records, key=lambda item: float(item.get("mtime", 0.0))):
                    if total <= max_bytes:
                        break
                    remove_cache_record(record)
                    total -= int(record.get("size", 0))

        cleanup_orphan_cache_metadata()
    finally:
        _cache_cleanup_lock.release()
