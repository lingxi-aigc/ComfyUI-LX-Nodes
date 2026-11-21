# -*- coding: utf-8 -*-
from __future__ import annotations

import hashlib
import json
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

import torch
import comfy.utils  # type: ignore[reportMissingImports]
from PIL import Image, ImageDraw, ImageFont

from ..categories import LX_RELAY_CATEGORY
from ..lingxi_bridge.lb_cache_paths import get_cache_dir
from ..lingxi_bridge.lb_config import API_PATHS
from ..lingxi_bridge.lb_image import (
    GPT_IMAGE2_QUALITIES,
    GPT_IMAGE2_MODERATIONS,
    IMAGE_RATIOS_BY_PLATFORM,
    IMAGE_RATIOS,
    IMAGE_SIZES,
    LingxiBridgeImage,
)
from ..lingxi_bridge.lb_aipaiai import (
    aipaiai_cache_fields,
    AIPAI_ADOBE_FORMAT,
    is_aipaiai_adobe,
    is_aipaiai_base_url,
    normalize_aipaiai_base_url,
)
from ..lingxi_bridge.lb_utils import pil2tensor, tensor2pil


MAX_SLOTS = 8
CACHE_DIR = get_cache_dir("concurrent_bridge")
CACHE_MAX_MB_ENV = "LX_CONCURRENT_CACHE_MAX_MB"
CACHE_MAX_DAYS_ENV = "LX_CONCURRENT_CACHE_MAX_DAYS"
DEFAULT_CACHE_MAX_MB = 512
DEFAULT_CACHE_MAX_DAYS = 7
CACHE_CLEANUP_INTERVAL_SECONDS = 300
EMPTY_SIZE = (512, 512)
DEFAULT_PLACEHOLDER_SIZE = (1024, 1024)
_cache_cleanup_lock = threading.Lock()
_last_cache_cleanup = 0.0


def _update_progress(pbar: Any, done: int, total: int) -> None:
    if pbar is None or total <= 0:
        return
    pbar.update_absolute(min(100, max(0, int(round(done * 100 / total)))))


@dataclass
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
        return _hash_text(self.api_key)

    def key_identity(self) -> str:
        return _sha_json(
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
        return _sha_json(self.semantic_fingerprint())

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


def _hash_text(value: object) -> str:
    text = "" if value is None else str(value)
    return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()[:16]


def _sha_json(data: object) -> str:
    raw = json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8", errors="replace")).hexdigest()


def _safe_json_loads(value: object) -> dict[str, Any]:
    if not isinstance(value, str) or not value.strip():
        return {}
    try:
        data = json.loads(value)
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _clean_str(value: object) -> str:
    return "" if value is None else str(value).strip()


def _clip(value: object, limit: int = 500) -> str:
    text = "" if value is None else str(value)
    return text if len(text) <= limit else text[:limit] + "..."


def _tensor_hash(tensor: torch.Tensor) -> str:
    t = tensor.detach().cpu().contiguous()
    arr = t.numpy()
    digest = hashlib.sha256()
    digest.update(str(tuple(arr.shape)).encode("ascii", errors="ignore"))
    digest.update(arr.tobytes())
    return digest.hexdigest()


def _image_group_hash(images: list[torch.Tensor]) -> str:
    payload = []
    for index, image in enumerate(images, start=1):
        payload.append({"index": index, "hash": _tensor_hash(image)})
    return _sha_json(payload)


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name, "")
    if not raw.strip():
        return default
    try:
        return max(0, int(float(raw)))
    except (TypeError, ValueError):
        return default


def _cache_max_bytes() -> int:
    return _env_int(CACHE_MAX_MB_ENV, DEFAULT_CACHE_MAX_MB) * 1024 * 1024


def _cache_max_age_seconds() -> int:
    return _env_int(CACHE_MAX_DAYS_ENV, DEFAULT_CACHE_MAX_DAYS) * 24 * 60 * 60


def _safe_file_size(path: str) -> int:
    try:
        return os.path.getsize(path) if os.path.isfile(path) else 0
    except OSError:
        return 0


def _touch_cache_files(*paths: str) -> None:
    now = time.time()
    for path in paths:
        try:
            if path and os.path.exists(path):
                os.utime(path, (now, now))
        except OSError:
            pass


def _remove_file(path: str) -> None:
    try:
        if path and os.path.isfile(path):
            os.remove(path)
    except OSError:
        pass


def _cache_records() -> list[dict[str, Any]]:
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
                    "size": int(stat.st_size) + _safe_file_size(meta_path),
                    "mtime": float(stat.st_mtime),
                }
            )
    return records


def _remove_cache_record(record: dict[str, Any]) -> None:
    _remove_file(str(record.get("image_path") or ""))
    _remove_file(str(record.get("meta_path") or ""))


def _cleanup_orphan_cache_metadata() -> None:
    if not os.path.isdir(CACHE_DIR):
        return
    for current, _dirs, files in os.walk(CACHE_DIR):
        for name in files:
            if not name.lower().endswith(".json"):
                continue
            meta_path = os.path.join(current, name)
            image_path = os.path.splitext(meta_path)[0] + ".png"
            if not os.path.isfile(image_path):
                _remove_file(meta_path)


def _cleanup_cache(force: bool = False) -> None:
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

        records = _cache_records()
        if not records:
            _cleanup_orphan_cache_metadata()
            return

        max_age = _cache_max_age_seconds()
        if max_age > 0:
            cutoff = now - max_age
            kept: list[dict[str, Any]] = []
            for record in records:
                if float(record.get("mtime", 0.0)) < cutoff:
                    _remove_cache_record(record)
                else:
                    kept.append(record)
            records = kept

        max_bytes = _cache_max_bytes()
        if max_bytes > 0:
            total = sum(int(record.get("size", 0)) for record in records)
            if total > max_bytes:
                for record in sorted(records, key=lambda item: float(item.get("mtime", 0.0))):
                    if total <= max_bytes:
                        break
                    _remove_cache_record(record)
                    total -= int(record.get("size", 0))

        _cleanup_orphan_cache_metadata()
    finally:
        _cache_cleanup_lock.release()


def _parse_info_channel(value: object, slot: int) -> Channel | None:
    data = _safe_json_loads(value)
    if not data:
        return None
    api_key = _clean_str(data.get("apikey") or data.get("api_key"))
    api_base = _clean_str(data.get("api_base")).rstrip("/")
    api_format = _clean_str(data.get("api_format") or "v1/images")
    model = _clean_str(data.get("model"))
    platform = _clean_str(data.get("platform") or "banana-pro")
    if not any([api_key, api_base, api_format, model, platform]):
        return None
    return Channel(
        source=f"info{slot}",
        api_index=slot,
        platform=platform,
        api_base=api_base,
        api_format=api_format,
        model=model,
        api_key=api_key,
        origin_label=f"info{slot}",
    )


def _parse_api_pool(value: object) -> list[Channel]:
    data = _safe_json_loads(value)
    if not data or data.get("type") != "lingxi_api_pool":
        return []

    raw_channels = data.get("channels")
    if isinstance(raw_channels, list):
        channels: list[Channel] = []
        for index, item in enumerate(raw_channels, start=1):
            if not isinstance(item, dict):
                continue
            api_key = _clean_str(item.get("api_key") or item.get("apikey"))
            if not api_key or api_key.lower() in {"none", "null"}:
                continue
            try:
                api_index = int(item.get("api_index") or index)
            except (TypeError, ValueError):
                api_index = index
            channels.append(
                Channel(
                    source=_clean_str(item.get("source") or "api_pool"),
                    api_index=api_index,
                    platform=_clean_str(item.get("platform") or "banana-pro"),
                    api_base=_clean_str(item.get("api_base")).rstrip("/"),
                    api_format=_clean_str(item.get("api_format") or "v1/images"),
                    model=_clean_str(item.get("model")),
                    api_key=api_key,
                    origin_label=_clean_str(item.get("origin_label") or item.get("origin") or ""),
                )
            )
        return channels

    platform = _clean_str(data.get("platform") or "banana-pro")
    api_base = _clean_str(data.get("api_base")).rstrip("/")
    api_format = _clean_str(data.get("api_format") or "v1/images")
    model = _clean_str(data.get("model"))
    keys = data.get("api_keys") or []
    if not isinstance(keys, list):
        return []
    channels: list[Channel] = []
    for index, key in enumerate(keys, start=1):
        api_key = _clean_str(key)
        if not api_key or api_key.lower() in {"none", "null"}:
            continue
        channels.append(
            Channel(
                source="api_pool",
                api_index=index,
                platform=platform,
                api_base=api_base,
                api_format=api_format,
                model=model,
                api_key=api_key,
                origin_label=f"api_pool key {index}",
            )
        )
    return channels


def _cache_root(unique_id: object) -> str:
    node_id = _clean_str(unique_id) or "default"
    node_id = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in node_id)
    return os.path.join(CACHE_DIR, node_id)


def _cache_paths(unique_id: object, slot: int, input_hash: str) -> tuple[str, str]:
    root = _cache_root(unique_id)
    os.makedirs(root, exist_ok=True)
    base = os.path.join(root, f"slot_{slot}_{input_hash[:24]}")
    return base + ".png", base + ".json"


def _load_cached_image(unique_id: object, slot: int, input_hash: str) -> tuple[Image.Image | None, dict[str, Any]]:
    image_path, meta_path = _cache_paths(unique_id, slot, input_hash)
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
    _touch_cache_files(image_path, meta_path)
    return image, meta


def _save_cached_image(unique_id: object, slot: int, input_hash: str, image: Image.Image, meta: dict[str, Any]) -> None:
    image_path, meta_path = _cache_paths(unique_id, slot, input_hash)
    image.save(image_path, format="PNG")
    safe_meta = dict(meta)
    safe_meta.pop("api_key", None)
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(safe_meta, f, ensure_ascii=False, indent=2)
        f.write("\n")
    _cleanup_cache()


def _parse_response_json(value: object) -> dict[str, Any]:
    data = _safe_json_loads(value)
    return data if data else {}


KEY_FATAL_ERROR_CODES = {"HTTP_401", "HTTP_403", "HTTP_402", "API_KEY", "QUOTA"}
KEY_TRANSIENT_ERROR_CODES = {"HTTP_429", "RATE_LIMIT", "CONCURRENT_LIMIT", "TIMEOUT"}


def _response_message(data: dict[str, Any], fallback: object = "") -> str:
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


def _is_key_fatal_error(code: object, reason: object = "") -> bool:
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


def _is_key_transient_error(code: object, reason: object = "") -> bool:
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


def _should_failover_key(code: object, reason: object = "") -> bool:
    return _is_key_fatal_error(code, reason) or _is_key_transient_error(code, reason)


def _input_image_sizes(images: list[torch.Tensor]) -> list[dict[str, Any]]:
    sizes: list[dict[str, Any]] = []
    for index, image in enumerate(images, start=1):
        item: dict[str, Any] = {"index": index}
        try:
            pil = tensor2pil(image)[0]
            item.update(
                {
                    "width": int(pil.width),
                    "height": int(pil.height),
                    "size": f"{pil.width}x{pil.height}",
                }
            )
        except Exception:
            shape = getattr(image, "shape", None)
            if shape is not None:
                item["tensor_shape"] = [int(value) for value in tuple(shape)]
        sizes.append(item)
    return sizes


def _api_domain(api_base: object) -> str:
    text = _clean_str(api_base)
    if not text:
        return ""
    candidate = text if "://" in text else f"https://{text}"
    try:
        parts = urlsplit(candidate)
    except Exception:
        return text.split("/", 1)[0]
    return parts.netloc or parts.path.split("/", 1)[0]


def _join_endpoint(api_base: object, endpoint_path: object) -> str:
    base = normalize_aipaiai_base_url(_clean_str(api_base).rstrip("/"))
    path = _clean_str(endpoint_path)
    if not base:
        return path
    if not path:
        return base
    return f"{base}/{path.lstrip('/')}"


def _endpoint_path(channel: Channel, has_images: bool) -> str:
    paths = API_PATHS.get(f"image_{channel.api_format}", {})
    try:
        if channel.api_format == "runninghub-/openapi/v2":
            key = "edit" if has_images else "create"
            fallback = f"/openapi/v2/{channel.model}/image-to-image" if has_images else f"/openapi/v2/{channel.model}/text-to-image"
            return (paths.get(key) or fallback).format(model=channel.model)
        if channel.api_format == "v1beta/models":
            key = "edit" if has_images else "generate"
            return (paths.get(key) or "/v1beta/models/{model}:generateContent").format(model=channel.model)
        if channel.api_format == "v1/chat/completions":
            return paths.get("chat") or "/v1/chat/completions"
        if channel.api_format == "v1/api/generate":
            return paths.get("generate") or "/v1/api/generate"
        if channel.api_format in {"v1/images", AIPAI_ADOBE_FORMAT}:
            if channel.platform in {"gpt-image2", "gpt-image2.5"}:
                key = "gpt_image2_edit" if has_images else "gpt_image2_generate"
            else:
                key = "edit" if has_images else "generate"
            fallback = "/v1/images/edits" if has_images else "/v1/images/generations"
            return paths.get(key) or fallback
    except Exception:
        return ""
    return ""


def _effective_ratio(channel: Channel | None, ratio: str) -> str:
    if channel is None:
        return ratio
    allowed = IMAGE_RATIOS_BY_PLATFORM.get(channel.platform, IMAGE_RATIOS_BY_PLATFORM.get("banana-pro", ["auto"]))
    return ratio if ratio in allowed else "auto"


def _api_request_size(channel: Channel | None, ratio: str, size: str, images: list[torch.Tensor]) -> str:
    if channel is None or channel.platform not in {"gpt-image2", "gpt-image2.5"}:
        return size
    try:
        return LingxiBridgeImage()._gpt_image2_size(
            ratio,
            size,
            images,
            base_url=channel.api_base,
            adobe=is_aipaiai_adobe(channel.api_format, channel.model),
        )
    except Exception:
        return ""


def _parse_size_pair(value: object) -> tuple[int, int] | None:
    text = _clean_str(value).lower().replace("×", "x")
    if "x" not in text:
        return None
    left, right = text.split("x", 1)
    try:
        width = int(float(left.strip()))
        height = int(float(right.strip()))
    except ValueError:
        return None
    if width <= 0 or height <= 0:
        return None
    return width, height


def _corner_fill(image: Image.Image) -> tuple[int, int, int]:
    rgb = image.convert("RGB")
    width, height = rgb.size
    pixels = rgb.load()
    points = [
        pixels[0, 0],
        pixels[max(0, width - 1), 0],
        pixels[0, max(0, height - 1)],
        pixels[max(0, width - 1), max(0, height - 1)],
    ]
    return tuple(int(sum(pixel[index] for pixel in points) / len(points)) for index in range(3))


def _fit_on_canvas(image: Image.Image, canvas_size: tuple[int, int]) -> Image.Image:
    canvas_width, canvas_height = canvas_size
    source = image.convert("RGB")
    source_width, source_height = source.size
    if source_width <= 0 or source_height <= 0:
        return Image.new("RGB", canvas_size, (255, 255, 255))

    scale = min(canvas_width / source_width, canvas_height / source_height)
    resized_width = max(1, int(round(source_width * scale)))
    resized_height = max(1, int(round(source_height * scale)))
    resized = source.resize((resized_width, resized_height), Image.LANCZOS)

    canvas = Image.new("RGB", canvas_size, _corner_fill(source))
    offset = ((canvas_width - resized_width) // 2, (canvas_height - resized_height) // 2)
    canvas.paste(resized, offset)
    return canvas


def _prepare_reference_images(
    images: list[torch.Tensor],
    channel: Channel,
    ratio: str,
    api_request_size: str,
) -> tuple[list[torch.Tensor], bool, str]:
    if channel.platform not in {"gpt-image2", "gpt-image2.5"} or is_aipaiai_base_url(channel.api_base) or ratio == "auto" or not images:
        return images, False, ""

    canvas_size = _parse_size_pair(api_request_size)
    if canvas_size is None:
        return images, False, ""

    prepared: list[torch.Tensor] = []
    changed = False
    for image in images:
        try:
            pil = tensor2pil(image)[0]
        except Exception:
            prepared.append(image)
            continue
        if pil.size == canvas_size:
            prepared.append(image)
            continue
        prepared.append(pil2tensor(_fit_on_canvas(pil, canvas_size)))
        changed = True

    return prepared, changed, f"{canvas_size[0]}x{canvas_size[1]}"


def _prompt_with_ratio_hint(prompt: object, ratio: str, api_request_size: str, prepared: bool) -> str:
    text = _clean_str(prompt)
    if not prepared or ratio == "auto":
        return text
    size_hint = f"，输出画布按 {api_request_size}" if api_request_size else ""
    return (
        f"请生成宽高比为 {ratio} 的完整图片{size_hint}，不要沿用参考图的原始画布比例。\n"
        f"{text}"
    ).strip()


def _api_diagnostics(channel: Channel | None, has_images: bool) -> dict[str, Any]:
    if channel is None:
        return {}
    endpoint_path = _endpoint_path(channel, has_images)
    return {
        "source": channel.source,
        "api_index": channel.api_index,
        "origin_label": channel.origin(),
        "platform": channel.platform,
        "api_base": channel.api_base,
        "api_domain": _api_domain(channel.api_base),
        "api_format": channel.api_format,
        "model": channel.model,
        "endpoint_path": endpoint_path,
        "endpoint": _join_endpoint(channel.api_base, endpoint_path),
        "api_key_hash": channel.fingerprint().get("api_key_hash", ""),
    }


def _request_payload_summary(
    prompt: str,
    channel: Channel | None,
    ratio: str,
    size: str,
    quality: str,
    moderation: str,
    api_request_size: str,
    image_count: int,
) -> dict[str, Any]:
    if channel is None:
        return {}
    has_images = image_count > 0
    if channel.api_format == "runninghub-/openapi/v2":
        return {
            "prompt": prompt,
            "aspectRatio": ratio if ratio and ratio != "auto" else "1:1",
            "resolution": {"1K": "1k", "2K": "2k", "4K": "4k"}.get(size.upper(), "2k"),
            "quality": quality or "medium",
            "imageUrls": f"{image_count} uploaded reference image url(s)" if has_images else [],
        }
    if channel.api_format == "v1/api/generate":
        return {
            "model": channel.model,
            "prompt": prompt,
            "images": f"{image_count} base64 PNG image(s)",
            "aspectRatio": ratio,
            "imageSize": size,
            "replyType": "json",
        }
    if channel.api_format == "v1beta/models":
        return {
            "model": channel.model,
            "contents": f"text prompt + {image_count} inline PNG image(s)",
            "prompt": prompt,
            "ratio_prompt_hint": bool(ratio and ratio != "auto"),
            "seed": 0,
        }
    if channel.api_format == "v1/chat/completions":
        return {
            "model": channel.model,
            "messages": f"text prompt + {image_count} image_url part(s)",
            "prompt": prompt,
            "ratio_prompt_hint": bool(ratio and ratio != "auto"),
            "max_tokens": 4096,
            "n": 1,
            "seed": 0,
        }
    if channel.platform in {"gpt-image2", "gpt-image2.5"} and channel.api_format in {"v1/images", AIPAI_ADOBE_FORMAT}:
        if is_aipaiai_base_url(channel.api_base):
            return {
                "model": channel.model,
                "prompt": prompt,
                "size": api_request_size,
                "n": 1,
                "quality": quality if is_aipaiai_adobe(channel.api_format, channel.model) else size,
                **({"resolution": size} if is_aipaiai_adobe(channel.api_format, channel.model) else {}),
                "response_format": "url",
                "images": f"{image_count} multipart PNG image(s)" if has_images else [],
            }
        return {
            "model": channel.model,
            "prompt": prompt,
            "size": api_request_size,
            "n": 1,
            "quality": quality,
            "moderation": moderation,
            "images": f"{image_count} multipart PNG image(s)" if has_images else [],
        }
    payload: dict[str, Any] = {
        "model": channel.model,
        "prompt": prompt,
        "response_format": "url",
        "image_size": size,
        "n": "1" if has_images else 1,
        "images": f"{image_count} multipart PNG image(s)" if has_images else [],
    }
    if ratio and ratio != "auto":
        payload["aspect_ratio"] = ratio
    return payload


def _slot_request_diagnostics(
    slot: int,
    prompt: str,
    channel: Channel | None,
    images: list[torch.Tensor],
    image_sizes: list[dict[str, Any]],
    ratio: str,
    size: str,
    quality: str,
    moderation: str,
    reference_canvas_prepared: bool = False,
    reference_canvas_size: str = "",
) -> dict[str, Any]:
    effective_ratio = _effective_ratio(channel, ratio)
    api_request_size = _api_request_size(channel, effective_ratio, size, images)
    image_count = len(images)
    request = {
        "slot": slot,
        "prompt": prompt,
        "prompt_length": len(prompt),
        "requested_ratio": ratio,
        "effective_ratio": effective_ratio,
        "size": size,
        "quality": quality,
        "format": "jpeg",
        "moderation": moderation,
        "seed": 0,
        "api_request_size": api_request_size,
        "reference_canvas_prepared": reference_canvas_prepared,
        "reference_canvas_size": reference_canvas_size,
        "reference_image_count": image_count,
        "reference_image_sizes": image_sizes,
        "payload": _request_payload_summary(
            prompt,
            channel,
            effective_ratio,
            size,
            quality,
            moderation,
            api_request_size,
            image_count,
        ),
    }
    return {
        "prompt": prompt,
        "requested_ratio": ratio,
        "ratio": effective_ratio,
        "size": size,
        "quality": quality,
        "format": "jpeg",
        "moderation": moderation,
        "seed": 0,
        "api_request_size": api_request_size,
        "reference_canvas_prepared": reference_canvas_prepared,
        "reference_canvas_size": reference_canvas_size,
        "input_image_count": image_count,
        "input_image_sizes": image_sizes,
        "api": _api_diagnostics(channel, image_count > 0),
        "request": request,
    }


def _find_url(value: object, depth: int = 0) -> str:
    if depth > 4:
        return ""
    if isinstance(value, str):
        text = value.strip()
        return text if text.startswith(("http://", "https://")) else ""
    if isinstance(value, dict):
        for key in ("url", "image_url", "output_url", "download_url", "file_url"):
            found = _find_url(value.get(key), depth + 1)
            if found:
                return found
        for nested in value.values():
            found = _find_url(nested, depth + 1)
            if found:
                return found
    if isinstance(value, list):
        for item in value:
            found = _find_url(item, depth + 1)
            if found:
                return found
    return ""


def _response_summary(response: object, image_url: object = "", output_size: object = "") -> dict[str, Any]:
    data = _parse_response_json(response)
    url = _clean_str(image_url) or _find_url(data)
    summary: dict[str, Any] = {}
    if url:
        summary["url"] = url
    if output_size:
        summary["output_size"] = output_size
    if data:
        for key in ("code", "status", "message", "type", "model", "api_format", "platform", "size", "ratio", "id", "error"):
            value = data.get(key)
            if value not in (None, ""):
                summary[key] = _clip(value, 800) if isinstance(value, str) else value
    raw = _clip(response, 1500)
    if raw:
        summary["raw"] = raw
    return summary


def _classify_error(response: object, explanation: object = "") -> tuple[str, str]:
    data = _parse_response_json(response)
    error = data.get("error")
    status = data.get("status")
    error_type = ""
    if isinstance(error, dict):
        status = status or error.get("status")
        error_type = _clean_str(error.get("type") or error.get("code"))
    message = _response_message(data, explanation or response)
    msg = _clip(message, 800)
    lower = f"{msg} {error_type}".lower()
    if any(token in lower for token in ("api key", "apikey", "authorization", "unauthorized", "forbidden", "invalid token", "invalid credential", "令牌", "权限", "授权")):
        code = "API_KEY"
    elif any(token in lower for token in ("balance", "quota", "credit", "billing", "insufficient", "欠费", "余额", "额度")):
        code = "QUOTA"
    elif any(token in lower for token in ("policy", "moderation", "safety", "sensitive", "unsafe", "安全", "敏感", "违规")):
        code = "CONTENT_POLICY"
    elif "429" in lower or "rate limit" in lower:
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


def _friendly_error(code: object, reason: object = "") -> str:
    code_text = "" if code is None else str(code)
    reason_text = _clip(reason, 180)
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


def _make_placeholder(size: tuple[int, int], title: str, detail: str = "", fill=(48, 48, 48)) -> Image.Image:
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
        lines.append(_clip(detail, 90))
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


def _blank_image(size: tuple[int, int]) -> Image.Image:
    return Image.new("RGB", size, (255, 255, 255))


def _resize_to(image: Image.Image, size: tuple[int, int]) -> Image.Image:
    if image.size == size:
        return image.convert("RGB")
    return image.convert("RGB").resize(size, Image.LANCZOS)


def _to_tensor(image: Image.Image) -> torch.Tensor:
    return pil2tensor(image.convert("RGB"))


def _batch_tensor(images: list[Image.Image], fallback_size: tuple[int, int]) -> torch.Tensor:
    if not images:
        images = [_blank_image(fallback_size)]
    target_size = images[0].size
    tensors = [_to_tensor(_resize_to(image, target_size)) for image in images]
    return torch.cat(tensors, dim=0)


def _long_image(images: list[Image.Image], fallback_size: tuple[int, int]) -> Image.Image:
    if not images:
        return _blank_image(fallback_size)
    width = images[0].width
    normalized = []
    for image in images:
        if image.width != width:
            ratio = width / max(1, image.width)
            height = max(1, int(round(image.height * ratio)))
            image = image.resize((width, height), Image.LANCZOS)
        normalized.append(image.convert("RGB"))
    total_height = sum(image.height for image in normalized)
    canvas = Image.new("RGB", (width, total_height), (255, 255, 255))
    y = 0
    for image in normalized:
        canvas.paste(image, (0, y))
        y += image.height
    return canvas


def _first_size(images: list[Image.Image]) -> tuple[int, int]:
    for image in images:
        if image is not None:
            return image.size
    return DEFAULT_PLACEHOLDER_SIZE


def _call_single_image(
    slot: int,
    prompt: str,
    channel: Channel,
    common_images: list[torch.Tensor],
    ratio: str,
    size: str,
    quality: str,
    moderation: str,
) -> dict[str, Any]:
    started = time.time()
    node = LingxiBridgeImage()
    effective_ratio = _effective_ratio(channel, ratio)
    api_request_size = _api_request_size(channel, effective_ratio, size, common_images)
    request_images, reference_canvas_prepared, reference_canvas_size = _prepare_reference_images(
        common_images,
        channel,
        effective_ratio,
        api_request_size,
    )
    request_prompt = _prompt_with_ratio_hint(
        prompt,
        effective_ratio,
        api_request_size,
        reference_canvas_prepared,
    )
    kwargs = {f"image{i}": image for i, image in enumerate(request_images, start=1)}
    try:
        image_tensor, response, image_url, explanation = node.generate_image(
            prompt=request_prompt,
            ratio=effective_ratio,
            size=size,
            quality=quality,
            format="jpeg",
            moderation=moderation,
            seed=0,
            info=channel.to_info_json(),
            **kwargs,
        )
        elapsed = time.time() - started
        if isinstance(image_tensor, torch.Tensor):
            pil = tensor2pil(image_tensor)[0]
            return {
                "slot": slot,
                "status": "generated",
                "image": pil,
                "response": response,
                "url": image_url or _parse_response_json(response).get("url", ""),
                "explanation": explanation,
                "elapsed": elapsed,
                "channel": channel,
                "api_request_size": api_request_size,
                "reference_canvas_prepared": reference_canvas_prepared,
                "reference_canvas_size": reference_canvas_size,
            }
        code, reason = _classify_error(response, explanation)
        return {
            "slot": slot,
            "status": "failed",
            "error_code": code,
            "error_reason": reason,
            "response": response,
            "explanation": explanation,
            "elapsed": elapsed,
            "channel": channel,
            "api_request_size": api_request_size,
            "reference_canvas_prepared": reference_canvas_prepared,
            "reference_canvas_size": reference_canvas_size,
        }
    except Exception as exc:
        elapsed = time.time() - started
        code, reason = _classify_error(str(exc), "")
        return {
            "slot": slot,
            "status": "failed",
            "error_code": code,
            "error_reason": reason,
            "response": "",
            "explanation": str(exc),
            "elapsed": elapsed,
            "channel": channel,
            "api_request_size": api_request_size,
            "reference_canvas_prepared": reference_canvas_prepared,
            "reference_canvas_size": reference_canvas_size,
        }


class KeyHealth:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._blocked: set[str] = set()
        self._records: dict[str, dict[str, Any]] = {}
        self._retry_records: list[dict[str, Any]] = []

    def choose(self, channels: list[Channel], tried: set[str]) -> Channel | None:
        with self._lock:
            for channel in channels:
                key = channel.key_identity()
                if key not in tried and key not in self._blocked:
                    return channel
        return None

    def mark_key_problem(self, channel: Channel, code: object, reason: object, slot_name: str) -> None:
        identity = channel.key_identity()
        reason_text = _clip(reason, 300)
        status = "bad" if _is_key_fatal_error(code, reason) else "limited"
        with self._lock:
            self._blocked.add(identity)
            record = self._records.setdefault(
                identity,
                {
                    **channel.public_status(),
                    "label": channel.display_label(),
                    "status": status,
                    "error_code": str(code or "ERROR"),
                    "error_reason": reason_text,
                    "slots": [],
                    "count": 0,
                },
            )
            record["status"] = status
            record["error_code"] = str(code or "ERROR")
            record["error_reason"] = reason_text
            record["count"] = int(record.get("count", 0)) + 1
            slots = record.setdefault("slots", [])
            if slot_name and slot_name not in slots:
                slots.append(slot_name)

    def add_retry_record(self, slot_name: str, attempts: list[dict[str, Any]], final_channel: Channel) -> None:
        if not attempts:
            return
        with self._lock:
            self._retry_records.append(
                {
                    "slot": slot_name,
                    "attempts": attempts,
                    "final_key": final_channel.public_status(),
                    "final_label": final_channel.display_label(),
                }
            )

    def bad_key_records(self) -> list[dict[str, Any]]:
        with self._lock:
            records = []
            for record in self._records.values():
                clean = dict(record)
                clean["slots"] = list(clean.get("slots", []))
                records.append(clean)
        return sorted(records, key=lambda item: (int(item.get("api_index", 0)), str(item.get("label", ""))))

    def retry_records(self) -> list[dict[str, Any]]:
        with self._lock:
            return [dict(item) for item in self._retry_records]


def _attempt_summary(channel: Channel, code: object, reason: object) -> dict[str, Any]:
    return {
        **channel.public_status(),
        "label": channel.display_label(),
        "error_code": str(code or "ERROR"),
        "error_reason": _clip(reason, 300),
    }


def _call_single_image_with_failover(
    slot: int,
    prompt: str,
    channels: list[Channel],
    common_images: list[torch.Tensor],
    ratio: str,
    size: str,
    quality: str,
    moderation: str,
    health: KeyHealth,
) -> dict[str, Any]:
    if not channels:
        return {
            "slot": slot,
            "status": "failed",
            "error_code": "NO_API",
            "error_reason": "No API channel available.",
            "elapsed": 0.0,
            "attempts": [],
        }

    tried: set[str] = set()
    attempts: list[dict[str, Any]] = []
    last_result: dict[str, Any] | None = None
    slot_name = f"image{slot}"

    while len(tried) < len(channels):
        channel = health.choose(channels, tried)
        if channel is None:
            break
        tried.add(channel.key_identity())
        result = _call_single_image(slot, prompt, channel, common_images, ratio, size, quality, moderation)
        last_result = result
        if result.get("status") == "generated":
            result["attempts"] = attempts
            result["retried"] = bool(attempts)
            health.add_retry_record(slot_name, attempts, channel)
            return result

        code = result.get("error_code", "ERROR")
        reason = result.get("error_reason", "")
        if _should_failover_key(code, reason):
            health.mark_key_problem(channel, code, reason, slot_name)
            attempts.append(_attempt_summary(channel, code, reason))
            continue

        result["attempts"] = attempts
        result["retried"] = bool(attempts)
        return result

    if last_result is not None:
        last_result["attempts"] = attempts
        last_result["retried"] = bool(attempts)
        return last_result

    return {
        "slot": slot,
        "status": "failed",
        "error_code": "NO_HEALTHY_API_KEY",
        "error_reason": "All candidate API keys were disabled before this slot could run.",
        "elapsed": 0.0,
        "attempts": attempts,
    }


class LingxiBridgeConcurrentImage:
    CATEGORY = f"{LX_RELAY_CATEGORY}/旧版"
    SEARCH_ALIASES = ("lx", "LX", "灵犀", "灵犀批量生图", "灵犀批量生图（旧版）", "批量生图", "concurrent image")
    RETURN_TYPES = ("IMAGE",) * 10 + ("STRING", "STRING")
    RETURN_NAMES = (
        "images",
        "image1",
        "image2",
        "image3",
        "image4",
        "image5",
        "image6",
        "image7",
        "image8",
        "long_image",
        "status",
        "status_json",
    )
    FUNCTION = "generate"
    SIZE = (520, 720)

    @classmethod
    def INPUT_TYPES(cls):
        optional: dict[str, Any] = {
            "api_pool": ("STRING", {"default": "", "forceInput": True}),
        }
        for index in range(1, MAX_SLOTS + 1):
            optional[f"image{index}"] = ("IMAGE",)
        for index in range(1, MAX_SLOTS + 1):
            optional[f"prompt{index}"] = ("STRING", {"default": "", "forceInput": True})

        required: dict[str, Any] = {
            "ratio": (IMAGE_RATIOS, {"default": "auto"}),
            "size": (IMAGE_SIZES, {"default": "2K"}),
            "quality": (GPT_IMAGE2_QUALITIES, {"default": "medium"}),
            "moderation": (GPT_IMAGE2_MODERATIONS, {"default": "low"}),
        }
        for index in range(1, MAX_SLOTS + 1):
            required[f"重新生成_图{index}"] = ("BOOLEAN", {"default": False})

        return {
            "required": required,
            "optional": optional,
            "hidden": {
                "unique_id": "UNIQUE_ID",
            },
        }

    @classmethod
    def VALIDATE_INPUTS(cls, **kwargs):
        return True

    @classmethod
    def IS_CHANGED(cls, **kwargs):
        return time.time()

    def _select_channels(self, kwargs: dict[str, Any], valid_slots: list[int]) -> dict[int, list[Channel]]:
        pool_channels = _parse_api_pool(kwargs.get("api_pool", ""))
        pool_cursor = 0
        result: dict[int, list[Channel]] = {}
        for slot in valid_slots:
            info_channel = _parse_info_channel(kwargs.get(f"info{slot}", ""), slot)
            if info_channel is not None:
                result[slot] = [info_channel]
                continue
            if pool_channels:
                preferred = pool_channels[pool_cursor % len(pool_channels)]
                pool_cursor += 1
                same_target = [
                    channel
                    for channel in pool_channels
                    if channel.semantic_identity() == preferred.semantic_identity()
                ]
                preferred_index = same_target.index(preferred) if preferred in same_target else 0
                result[slot] = same_target[preferred_index:] + same_target[:preferred_index]
            else:
                result[slot] = []
        return result

    def _slot_hash(
        self,
        slot: int,
        prompt: str,
        channel: Channel,
        image_hash: str,
        ratio: str,
        size: str,
        quality: str,
        moderation: str,
    ) -> str:
        is_aipaiai = is_aipaiai_base_url(channel.api_base)
        provider_fields = (
            aipaiai_cache_fields(size, is_aipaiai_adobe(channel.api_format, channel.model), quality)
            if is_aipaiai
            else {
                "provider_profile": "default_v1",
                "quality": quality,
                "moderation": moderation,
                "response_format": "",
            }
        )
        return _sha_json(
            {
                "cache_version": 2,
                "slot": slot,
                "prompt": prompt,
                "channel": channel.semantic_fingerprint(),
                "images": image_hash,
                "ratio": ratio,
                "size": size,
                **provider_fields,
                "request_behavior": (
                    "aipaiai_images_v1"
                    if is_aipaiai
                    else "gpt_image2_reference_canvas_v3"
                ),
            }
        )

    def generate(self, ratio, size, quality, moderation, unique_id=None, **kwargs):
        prompts = {
            index: _clean_str(kwargs.get(f"prompt{index}", ""))
            for index in range(1, MAX_SLOTS + 1)
        }
        valid_slots = [index for index, prompt in prompts.items() if prompt]

        common_images = [
            kwargs[f"image{index}"]
            for index in range(1, MAX_SLOTS + 1)
            if kwargs.get(f"image{index}") is not None
        ]
        common_image_sizes = _input_image_sizes(common_images)
        image_hash = _image_group_hash(common_images)

        regenerate_slots = {
            index
            for index in range(1, MAX_SLOTS + 1)
            if bool(kwargs.get(f"重新生成_图{index}", False))
        }

        channels = self._select_channels(kwargs, valid_slots)
        key_health = KeyHealth()
        slot_records: dict[int, dict[str, Any]] = {}
        pending: list[dict[str, Any]] = []
        cached_or_success_images: list[Image.Image] = []
        total_progress = len(valid_slots)
        completed_progress = 0
        pbar = comfy.utils.ProgressBar(100) if total_progress > 0 else None
        _update_progress(pbar, completed_progress, total_progress)

        for slot in valid_slots:
            candidate_channels = channels.get(slot, [])
            channel = candidate_channels[0] if candidate_channels else None
            request_diagnostics = _slot_request_diagnostics(
                slot,
                prompts[slot],
                channel,
                common_images,
                common_image_sizes,
                ratio,
                size,
                quality,
                moderation,
            )
            if channel is None:
                error_code = "NO_API"
                error_reason = "No api_pool or info input available for this slot."
                slot_records[slot] = {
                    "slot": slot,
                    "status": "failed",
                    "error_code": error_code,
                    "error_reason": error_reason,
                    "error": {
                        "code": error_code,
                        "reason": error_reason,
                        "friendly": _friendly_error(error_code, error_reason),
                    },
                    "elapsed": 0.0,
                    **request_diagnostics,
                }
                completed_progress += 1
                _update_progress(pbar, completed_progress, total_progress)
                continue

            input_hash = self._slot_hash(
                slot,
                prompts[slot],
                channel,
                image_hash,
                ratio,
                size,
                quality,
                moderation,
            )
            should_regenerate = slot in regenerate_slots
            cached_image, cached_meta = (None, {})
            if not should_regenerate:
                cached_image, cached_meta = _load_cached_image(unique_id, slot, input_hash)

            if cached_image is not None:
                cached_or_success_images.append(cached_image)
                status = {
                    "slot": slot,
                    "status": "cached",
                    "elapsed": 0.0,
                    "input_hash": input_hash,
                    **request_diagnostics,
                }
                status.update({k: v for k, v in cached_meta.items() if k not in {"status", "slot", "input_hash"}})
                status.update(request_diagnostics)
                status.setdefault("output_size", f"{cached_image.width}x{cached_image.height}")
                slot_records[slot] = {**status, "image": cached_image}
                completed_progress += 1
                _update_progress(pbar, completed_progress, total_progress)
                continue

            pending.append(
                {
                    "slot": slot,
                    "prompt": prompts[slot],
                    "channels": candidate_channels,
                    "input_hash": input_hash,
                    "request_diagnostics": request_diagnostics,
                }
            )

        if pending:
            max_workers = max(1, min(MAX_SLOTS, len(pending)))
            with ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="LingxiConcurrent") as executor:
                future_map = {
                    executor.submit(
                        _call_single_image_with_failover,
                        item["slot"],
                        item["prompt"],
                        item["channels"],
                        common_images,
                        ratio,
                        size,
                        quality,
                        moderation,
                        key_health,
                    ): item
                    for item in pending
                }
                for future in as_completed(future_map):
                    item = future_map[future]
                    slot = item["slot"]
                    fallback_channel = item["channels"][0] if item.get("channels") else None
                    try:
                        result = future.result()
                    except Exception as exc:
                        code, reason = _classify_error(str(exc), "")
                        result = {
                            "slot": slot,
                            "status": "failed",
                            "error_code": code,
                            "error_reason": reason,
                            "response": "",
                            "explanation": str(exc),
                            "elapsed": 0.0,
                            "channel": fallback_channel,
                        }

                    channel = result.get("channel") if isinstance(result.get("channel"), Channel) else fallback_channel
                    public = channel.public_status() if isinstance(channel, Channel) else {}
                    request_diagnostics = item.get("request_diagnostics", {})
                    record = {
                        "slot": slot,
                        "status": result.get("status", "failed"),
                        "elapsed": round(float(result.get("elapsed", 0.0)), 3),
                        "input_hash": item["input_hash"],
                        **request_diagnostics,
                        **public,
                    }
                    if isinstance(channel, Channel):
                        record["api"] = _api_diagnostics(channel, len(common_images) > 0)
                    attempts = result.get("attempts")
                    if isinstance(attempts, list) and attempts:
                        record["attempts"] = attempts
                        record["retried"] = True
                    if result.get("api_request_size"):
                        record["api_request_size"] = result.get("api_request_size")
                        if isinstance(record.get("request"), dict):
                            record["request"]["api_request_size"] = result.get("api_request_size")
                            record["request"]["payload"] = _request_payload_summary(
                                item["prompt"],
                                channel,
                                record.get("ratio", ratio),
                                size,
                                quality,
                                moderation,
                                str(result.get("api_request_size") or ""),
                                len(common_images),
                            )
                    if "reference_canvas_prepared" in result:
                        record["reference_canvas_prepared"] = bool(result.get("reference_canvas_prepared"))
                        if isinstance(record.get("request"), dict):
                            record["request"]["reference_canvas_prepared"] = bool(result.get("reference_canvas_prepared"))
                    if result.get("reference_canvas_size"):
                        record["reference_canvas_size"] = result.get("reference_canvas_size")
                        if isinstance(record.get("request"), dict):
                            record["request"]["reference_canvas_size"] = result.get("reference_canvas_size")
                    if result.get("status") == "generated" and isinstance(result.get("image"), Image.Image):
                        image = result["image"].convert("RGB")
                        output_size = f"{image.width}x{image.height}"
                        target_size = str(record.get("api_request_size") or result.get("api_request_size") or "")
                        output_size_mismatch = bool(target_size and target_size != output_size)
                        url = result.get("url", "")
                        record["image"] = image
                        record["url"] = url
                        record["output_size"] = output_size
                        record["output_size_mismatch"] = output_size_mismatch
                        response_summary = _response_summary(result.get("response", ""), url, output_size)
                        if response_summary:
                            record["response"] = response_summary
                            record["response_ratio"] = response_summary.get("ratio", "")
                            record["response_size"] = response_summary.get("size", "")
                        cached_or_success_images.append(image)
                        _save_cached_image(
                            unique_id,
                            slot,
                            item["input_hash"],
                            image,
                            {k: v for k, v in record.items() if k != "image"},
                        )
                    else:
                        record["status"] = "failed"
                        error_code = result.get("error_code", "ERROR")
                        error_reason = _clip(result.get("error_reason", "Generation failed."))
                        record["error_code"] = error_code
                        record["error_reason"] = error_reason
                        record["error"] = {
                            "code": error_code,
                            "reason": error_reason,
                            "friendly": _friendly_error(error_code, error_reason),
                        }
                        raw_error = _clip(result.get("response") or result.get("explanation") or "")
                        if raw_error:
                            record["raw_error"] = raw_error
                        response_summary = _response_summary(result.get("response", ""))
                        if response_summary:
                            record["response"] = response_summary
                        if result.get("explanation"):
                            record["explanation"] = _clip(result.get("explanation"), 1500)
                    slot_records[slot] = record
                    completed_progress += 1
                    _update_progress(pbar, completed_progress, total_progress)

        _update_progress(pbar, total_progress, total_progress)

        target_size = _first_size(cached_or_success_images)
        output_by_slot: dict[int, Image.Image] = {}
        for slot in range(1, MAX_SLOTS + 1):
            record = slot_records.get(slot)
            if record and isinstance(record.get("image"), Image.Image):
                output_by_slot[slot] = record["image"].convert("RGB")
            elif slot in valid_slots:
                reason = ""
                if record:
                    reason = record.get("error_code") or record.get("error_reason") or ""
                output_by_slot[slot] = _make_placeholder(target_size, f"image{slot} failed", reason)
            else:
                output_by_slot[slot] = _blank_image(target_size if valid_slots else EMPTY_SIZE)

        valid_images = [output_by_slot[slot] for slot in valid_slots]
        images_tensor = _batch_tensor(valid_images, target_size if valid_slots else EMPTY_SIZE)
        single_tensors = [_to_tensor(output_by_slot[slot]) for slot in range(1, MAX_SLOTS + 1)]
        long_tensor = _to_tensor(_long_image(valid_images, target_size if valid_slots else EMPTY_SIZE))

        status_lines = []
        slots_json = []
        success = failed = cached = 0
        for slot in valid_slots:
            record = slot_records.get(slot, {"slot": slot, "status": "failed", "error_code": "UNKNOWN"})
            clean_record = {k: v for k, v in record.items() if k != "image"}
            slots_json.append(clean_record)
            state = record.get("status", "failed")
            if state == "generated":
                success += 1
                status_lines.append(
                    f"image{slot}：已生成，用时 {record.get('elapsed', 0.0)} 秒，"
                    f"通道 {record.get('source', '')} #{record.get('api_index', '')}"
                )
            elif state == "cached":
                cached += 1
                success += 1
                status_lines.append(f"image{slot}：已缓存")
            else:
                failed += 1
                status_lines.append(
                    f"image{slot}：生成失败，"
                    f"{_friendly_error(record.get('error_code', 'ERROR'), record.get('error_reason', ''))}"
                )

        bad_keys = key_health.bad_key_records()
        retry_records = key_health.retry_records()
        if bad_keys:
            status_lines.append("")
            status_lines.append("问题 API Key：")
            for key_record in bad_keys[:12]:
                slots = ", ".join(str(item) for item in key_record.get("slots", [])[:8]) or "-"
                status_lines.append(
                    f"- {key_record.get('label', '')}："
                    f"{_friendly_error(key_record.get('error_code', 'ERROR'), key_record.get('error_reason', ''))}；"
                    f"本轮已跳过；影响图片：{slots}"
                )
            if len(bad_keys) > 12:
                status_lines.append(f"- 还有 {len(bad_keys) - 12} 个问题 Key，详见 status_json。")
        if retry_records:
            status_lines.append("")
            status_lines.append("重试记录：")
            for retry in retry_records[:12]:
                attempt_labels = [
                    str(attempt.get("label") or f"Key #{attempt.get('api_index', '')}")
                    for attempt in retry.get("attempts", [])
                ]
                chain = " -> ".join(attempt_labels + [str(retry.get("final_label", ""))])
                status_lines.append(f"- {retry.get('slot', '')}：{chain} 成功")
            if len(retry_records) > 12:
                status_lines.append(f"- 还有 {len(retry_records) - 12} 条重试记录，详见 status_json。")

        if not valid_slots:
            status_lines.append("没有有效提示词。")

        api_channels = []
        for item in slots_json:
            api_info = item.get("api")
            if isinstance(api_info, dict) and api_info:
                api_channels.append({"slot": item.get("slot"), **api_info})

        status_payload = {
            "type": "lx_concurrent_image_status",
            "version": 2,
            "node": "LingxiBridgeConcurrentImage",
            "total": len(valid_slots),
            "success": success,
            "failed": failed,
            "cached": cached,
            "settings": {
                "ratio": ratio,
                "size": size,
                "quality": quality,
                "format": "jpeg",
                "moderation": moderation,
                "seed": 0,
                "reference_image_count": len(common_images),
                "reference_image_sizes": common_image_sizes,
            },
            "api_channels": api_channels,
            "bad_keys": bad_keys,
            "retry_records": retry_records,
            "key_failover_count": len(retry_records),
            "slots": slots_json,
        }
        status_text = "\n".join(status_lines)
        status_json = json.dumps(status_payload, ensure_ascii=False, indent=2)

        return (
            images_tensor,
            *single_tensors,
            long_tensor,
            status_text,
            status_json,
        )
