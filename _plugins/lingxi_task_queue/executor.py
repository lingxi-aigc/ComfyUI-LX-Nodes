# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

import torch
import comfy.utils  # type: ignore[reportMissingImports]
from PIL import Image

from ..categories import LX_RELAY_CATEGORY
from ..lingxi_bridge.lb_image import (
    IMAGE_RATIOS_BY_PLATFORM,
    LingxiBridgeImage,
)
from ..lingxi_bridge.lb_aipaiai import (
    aipaiai_cache_fields,
    is_aipaiai_adobe,
    is_aipaiai_base_url,
)
from ..lingxi_bridge.lb_utils import pil2tensor, tensor2pil
from .shared import (
    MAX_TASKS,
    RESULTS_TYPE,
    TASKS_TYPE,
    Channel,
    batch_tensor,
    blank_image,
    classify_error,
    clean_str,
    clip,
    first_image_size,
    friendly_error,
    hash_text,
    image_group_hash,
    is_key_fatal_error,
    load_cached_image,
    long_image,
    make_placeholder,
    normalize_tasks,
    parse_api_channels,
    parse_response_json,
    save_cached_image,
    sha_json,
    should_failover_key,
    to_tensor,
)


CONCURRENCY_OPTIONS = ["自动"] + [str(index) for index in range(1, MAX_TASKS + 1)]
CONCURRENCY_ERROR_CODES = {"HTTP_429", "RATE_LIMIT", "CONCURRENT_LIMIT", "TIMEOUT"}


def _update_progress(pbar: Any, done: int, total: int) -> None:
    if pbar is None or total <= 0:
        return
    pbar.update_absolute(min(100, max(0, int(round(done * 100 / total)))))


def _ratio_number(value: object) -> float | None:
    text = clean_str(value)
    if not text or text == "auto" or ":" not in text:
        return None
    left, right = text.split(":", 1)
    try:
        width = float(left.strip())
        height = float(right.strip())
    except ValueError:
        return None
    if width <= 0 or height <= 0:
        return None
    return width / height


def _api_request_size(task: dict[str, Any], channel: Channel, ratio: str) -> str:
    size = clean_str(task.get("size") or "2K")
    if channel.platform not in {"gpt-image2", "gpt-image2.5"}:
        return size
    try:
        return LingxiBridgeImage()._gpt_image2_size(
            ratio,
            size,
            task.get("images", []),
            base_url=channel.api_base,
            adobe=is_aipaiai_adobe(channel.api_format, channel.model),
        )
    except Exception:
        return ""


def _parse_size_pair(value: object) -> tuple[int, int] | None:
    text = clean_str(value).lower().replace("×", "x")
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
    text = clean_str(prompt)
    if not prepared or ratio == "auto":
        return text
    size_hint = f"，输出画布按 {api_request_size}" if api_request_size else ""
    return (
        f"请生成宽高比为 {ratio} 的完整图片{size_hint}，不要沿用参考图的原始画布比例。\n"
        f"{text}"
    ).strip()


def _ratio_mismatch_detail(item: dict[str, Any], image: Image.Image) -> str:
    expected = _ratio_number(item.get("ratio"))
    if expected is None:
        return ""
    width, height = image.size
    if width <= 0 or height <= 0:
        return ""
    actual = width / height
    if abs(actual - expected) / expected <= 0.08:
        return ""
    name = item.get("name") or f"task{item.get('index', '')}"
    return (
        f"{name}: requested {item.get('ratio')}, "
        f"api_size {item.get('api_request_size') or '-'}, output {width}x{height}"
    )


def _pixel_size_mismatch_detail(item: dict[str, Any], image: Image.Image) -> str:
    expected = _parse_size_pair(item.get("api_request_size"))
    if expected is None:
        return ""
    output_size = (image.width, image.height)
    if output_size == expected:
        return ""
    name = item.get("name") or f"task{item.get('index', '')}"
    return f"{name}: requested pixels {expected[0]}x{expected[1]}, output {image.width}x{image.height}"


def _select_concurrency(value: object, pending_count: int) -> int:
    text = clean_str(value)
    if not text or text == "自动":
        return max(1, min(MAX_TASKS, pending_count))
    try:
        count = int(float(text))
    except (TypeError, ValueError):
        count = pending_count
    return max(1, min(MAX_TASKS, count, max(1, pending_count)))


def _normalized_ratio(channel: Channel, ratio: str) -> tuple[str, str]:
    allowed = IMAGE_RATIOS_BY_PLATFORM.get(channel.platform, IMAGE_RATIOS_BY_PLATFORM.get("banana-pro", ["auto"]))
    if ratio in allowed:
        return ratio, ""
    return "auto", f"比例 {ratio} 不适用于 {channel.platform}，已回退 auto。"


def _task_hash(task: dict[str, Any], channel: Channel, ratio: str) -> str:
    is_aipaiai = is_aipaiai_base_url(channel.api_base)
    provider_fields = (
        aipaiai_cache_fields(task.get("size", "2K"), is_aipaiai_adobe(channel.api_format, channel.model), task.get("quality", "medium"))
        if is_aipaiai
        else {
            "provider_profile": "default_v1",
            "quality": task.get("quality", "medium"),
            "moderation": task.get("moderation", "low"),
            "response_format": "",
        }
    )
    return sha_json(
        {
            "cache_version": 2,
            "task_id": task.get("task_id") or task.get("index"),
            "prompt": task.get("prompt", ""),
            "images": image_group_hash(task.get("images", [])),
            "ratio": ratio,
            "size": task.get("size", "2K"),
            **provider_fields,
            "request_behavior": (
                "aipaiai_images_v1"
                if is_aipaiai
                else (
                    "gpt_image2_reference_canvas_v3"
                    if channel.platform in {"gpt-image2", "gpt-image2.5"} and ratio != "auto" and task.get("images")
                    else "default_v1"
                )
            ),
            "channel": channel.semantic_fingerprint(),
        }
    )


def _reported_quality(task: dict[str, Any], channel: Channel | None) -> str:
    if channel is not None and is_aipaiai_base_url(channel.api_base) and not is_aipaiai_adobe(channel.api_format, channel.model):
        return clean_str(task.get("size") or "2K").upper()
    return clean_str(task.get("quality") or "medium")


def _reported_moderation(task: dict[str, Any], channel: Channel | None) -> str:
    if channel is not None and is_aipaiai_base_url(channel.api_base) and not is_aipaiai_adobe(channel.api_format, channel.model):
        return ""
    return clean_str(task.get("moderation") or "low")


def _call_task(task: dict[str, Any], channel: Channel, ratio: str, api_request_size: str) -> dict[str, Any]:
    started = time.time()
    node = LingxiBridgeImage()
    images = task.get("images", [])
    request_images, reference_canvas_prepared, reference_canvas_size = _prepare_reference_images(
        images,
        channel,
        ratio,
        api_request_size,
    )
    kwargs = {f"image{i}": image for i, image in enumerate(request_images, start=1)}
    request_prompt = _prompt_with_ratio_hint(
        task.get("prompt", ""),
        ratio,
        api_request_size,
        reference_canvas_prepared,
    )
    try:
        image_tensor, response, image_url, explanation = node.generate_image(
            prompt=request_prompt,
            ratio=ratio,
            size=task.get("size", "2K"),
            quality=task.get("quality", "medium"),
            format="jpeg",
            moderation=task.get("moderation", "low"),
            seed=0,
            info=channel.to_info_json(),
            **kwargs,
        )
        elapsed = time.time() - started
        if isinstance(image_tensor, torch.Tensor):
            pil = tensor2pil(image_tensor)[0]
            response_json = parse_response_json(response)
            return {
                "status": "generated",
                "image": pil,
                "response": response,
                "url": image_url or parse_response_json(response).get("url", ""),
                "explanation": explanation,
                "elapsed": elapsed,
                "channel": channel,
                "api_request_size": api_request_size,
                "response_ratio": response_json.get("ratio", ""),
                "response_size": response_json.get("size", ""),
                "requested_size_pixels": response_json.get("requested_size_pixels", ""),
                "original_output_size": response_json.get("original_output_size", ""),
                "response_output_size_mismatch": bool(response_json.get("output_size_mismatch", False)),
                "output_size": f"{pil.width}x{pil.height}",
                "reference_canvas_prepared": reference_canvas_prepared,
                "reference_canvas_size": reference_canvas_size,
            }
        code, reason = classify_error(response, explanation)
        return {
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
        code, reason = classify_error(str(exc), "")
        return {
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

    def mark_key_problem(self, channel: Channel, code: object, reason: object, task_name: str) -> None:
        identity = channel.key_identity()
        reason_text = clip(reason, 300)
        status = "bad" if is_key_fatal_error(code, reason) else "limited"
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
                    "tasks": [],
                    "count": 0,
                },
            )
            record["status"] = status
            record["error_code"] = str(code or "ERROR")
            record["error_reason"] = reason_text
            record["count"] = int(record.get("count", 0)) + 1
            tasks = record.setdefault("tasks", [])
            if task_name and task_name not in tasks:
                tasks.append(task_name)

    def add_retry_record(self, task_name: str, attempts: list[dict[str, Any]], final_channel: Channel) -> None:
        if not attempts:
            return
        with self._lock:
            self._retry_records.append(
                {
                    "task": task_name,
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
                clean["tasks"] = list(clean.get("tasks", []))
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
        "error_reason": clip(reason, 300),
    }


def _call_task_with_failover(
    task: dict[str, Any],
    channels: list[Channel],
    ratio: str,
    api_request_size: str,
    health: KeyHealth,
    task_name: str,
) -> dict[str, Any]:
    if not channels:
        return {
            "status": "failed",
            "error_code": "NO_API",
            "error_reason": "No API channel available.",
            "elapsed": 0.0,
            "api_request_size": api_request_size,
            "attempts": [],
        }

    tried: set[str] = set()
    attempts: list[dict[str, Any]] = []
    last_result: dict[str, Any] | None = None

    while len(tried) < len(channels):
        channel = health.choose(channels, tried)
        if channel is None:
            break
        tried.add(channel.key_identity())
        result = _call_task(task, channel, ratio, api_request_size)
        last_result = result
        if result.get("status") == "generated":
            result["attempts"] = attempts
            result["retried"] = bool(attempts)
            health.add_retry_record(task_name, attempts, channel)
            return result

        code = result.get("error_code", "ERROR")
        reason = result.get("error_reason", "")
        if should_failover_key(code, reason):
            health.mark_key_problem(channel, code, reason, task_name)
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
        "status": "failed",
        "error_code": "NO_HEALTHY_API_KEY",
        "error_reason": "All candidate API keys were disabled before this task could run.",
        "elapsed": 0.0,
        "api_request_size": api_request_size,
        "attempts": attempts,
    }


class LingxiBatchExecute:
    CATEGORY = f"{LX_RELAY_CATEGORY}/任务批量"
    RETURN_TYPES = ("IMAGE", "IMAGE", RESULTS_TYPE, "STRING", "STRING")
    RETURN_NAMES = ("images", "long_image", "results", "status", "status_json")
    FUNCTION = "execute"
    SIZE = (440, 260)
    SEARCH_ALIASES = ("lx", "LX", "灵犀", "灵犀批量执行", "任务队列", "批量执行", "并发生图")

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "tasks": (TASKS_TYPE,),
                "并发数量": (CONCURRENCY_OPTIONS, {"default": "自动"}),
                "全部重新生成": ("BOOLEAN", {"default": False}),
            },
            "optional": {
                "默认API": ("STRING", {"default": "", "forceInput": True}),
            },
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

    def _select_channels(self, tasks: list[dict[str, Any]], default_api: object) -> dict[int, list[Channel]]:
        result: dict[int, list[Channel]] = {}
        for position, task in enumerate(tasks, start=1):
            api_value = task.get("api") or default_api or ""
            channels = parse_api_channels(api_value, f"task{position}")
            if not channels:
                result[position] = []
                continue
            stable_id = clean_str(task.get("task_id")) or str(position)
            channel_index = int(hash_text(stable_id), 16) % len(channels)
            preferred = channels[channel_index]
            same_target = [
                channel
                for channel in channels
                if channel.semantic_identity() == preferred.semantic_identity()
            ]
            preferred_index = same_target.index(preferred) if preferred in same_target else 0
            result[position] = same_target[preferred_index:] + same_target[:preferred_index]
        return result

    def execute(self, tasks, 并发数量="自动", 全部重新生成=False, 默认API="", unique_id=None):
        all_tasks = normalize_tasks(tasks)[:MAX_TASKS]
        valid_tasks = [
            task
            for task in all_tasks
            if task.get("enabled", True) and clean_str(task.get("prompt"))
        ]
        channels = self._select_channels(valid_tasks, 默认API)
        key_health = KeyHealth()
        records: dict[int, dict[str, Any]] = {}
        pending: list[dict[str, Any]] = []
        ready_images: list[Image.Image] = []
        api_key_hashes: set[str] = set()
        ratio_warnings: list[str] = []
        total_progress = len(valid_tasks)
        completed_progress = 0
        pbar = comfy.utils.ProgressBar(100) if total_progress > 0 else None
        _update_progress(pbar, completed_progress, total_progress)

        for position, task in enumerate(valid_tasks, start=1):
            candidate_channels = channels.get(position, [])
            channel = candidate_channels[0] if candidate_channels else None
            if channel is None:
                records[position] = {
                    "index": position,
                    "task_id": task.get("task_id", ""),
                    "name": task.get("name") or f"任务{position}",
                    "prompt": task.get("prompt", ""),
                    "status": "failed",
                    "error_code": "NO_API",
                    "error_reason": "没有可用 API 配置。",
                    "elapsed": 0.0,
                }
                completed_progress += 1
                _update_progress(pbar, completed_progress, total_progress)
                continue

            api_key_hashes.update(candidate.key_hash() for candidate in candidate_channels)
            ratio, ratio_warning = _normalized_ratio(channel, clean_str(task.get("ratio") or "auto"))
            input_hash = _task_hash(task, channel, ratio)
            api_request_size = _api_request_size(task, channel, ratio)
            if ratio_warning:
                ratio_warnings.append(f"{task.get('name') or f'任务{position}'}：{ratio_warning}")
            should_regenerate = bool(全部重新生成 or task.get("regenerate"))
            cached_image, cached_meta = (None, {})
            if not should_regenerate:
                cached_image, cached_meta = load_cached_image(unique_id, input_hash)

            if cached_image is not None:
                ready_images.append(cached_image)
                record = {
                    "index": position,
                    "task_id": task.get("task_id", ""),
                    "name": task.get("name") or f"任务{position}",
                    "prompt": task.get("prompt", ""),
                    "status": "cached",
                    "cached": True,
                    "elapsed": 0.0,
                    "input_hash": input_hash,
                    "ratio": ratio,
                    "size": task.get("size", "2K"),
                    "quality": _reported_quality(task, channel),
                    "moderation": _reported_moderation(task, channel),
                    "api_request_size": api_request_size,
                    "reference_canvas_prepared": False,
                    "reference_canvas_size": "",
                    "image": cached_image,
                }
                record.update({k: v for k, v in cached_meta.items() if k not in {"status", "index", "input_hash", "image", "cached"}})
                records[position] = record
                completed_progress += 1
                _update_progress(pbar, completed_progress, total_progress)
                continue

            pending.append(
                {
                    "position": position,
                    "task": task,
                    "channels": candidate_channels,
                    "ratio": ratio,
                    "api_request_size": api_request_size,
                    "input_hash": input_hash,
                }
            )

        actual_concurrency = _select_concurrency(并发数量, len(pending)) if pending else 0
        if pending:
            with ThreadPoolExecutor(max_workers=actual_concurrency, thread_name_prefix="LingxiTaskQueue") as executor:
                future_map = {
                    executor.submit(
                        _call_task_with_failover,
                        item["task"],
                        item["channels"],
                        item["ratio"],
                        item["api_request_size"],
                        key_health,
                        item["task"].get("name") or f"task{item['position']}",
                    ): item
                    for item in pending
                }
                for future in as_completed(future_map):
                    item = future_map[future]
                    position = item["position"]
                    task = item["task"]
                    fallback_channel = item["channels"][0] if item.get("channels") else None
                    try:
                        result = future.result()
                    except Exception as exc:
                        code, reason = classify_error(str(exc), "")
                        result = {
                            "status": "failed",
                            "error_code": code,
                            "error_reason": reason,
                            "elapsed": 0.0,
                            "channel": fallback_channel,
                            "api_request_size": item.get("api_request_size", ""),
                            "reference_canvas_prepared": False,
                            "reference_canvas_size": "",
                        }

                    channel = result.get("channel") if isinstance(result.get("channel"), Channel) else fallback_channel
                    public = channel.public_status() if isinstance(channel, Channel) else {}
                    record = {
                        "index": position,
                        "task_id": task.get("task_id", ""),
                        "name": task.get("name") or f"任务{position}",
                        "prompt": task.get("prompt", ""),
                        "status": result.get("status", "failed"),
                        "cached": False,
                        "elapsed": round(float(result.get("elapsed", 0.0)), 3),
                        "input_hash": item["input_hash"],
                        "ratio": item["ratio"],
                        "size": task.get("size", "2K"),
                        "quality": _reported_quality(task, channel),
                        "moderation": _reported_moderation(task, channel),
                        "api_request_size": result.get("api_request_size") or item.get("api_request_size", ""),
                        "reference_canvas_prepared": bool(result.get("reference_canvas_prepared", False)),
                        "reference_canvas_size": result.get("reference_canvas_size", ""),
                        **public,
                    }
                    attempts = result.get("attempts")
                    if isinstance(attempts, list) and attempts:
                        record["attempts"] = attempts
                        record["retried"] = True
                    if result.get("status") == "generated" and isinstance(result.get("image"), Image.Image):
                        image = result["image"].convert("RGB")
                        record["image"] = image
                        record["url"] = result.get("url", "")
                        record["response_ratio"] = result.get("response_ratio", "")
                        record["response_size"] = result.get("response_size", "")
                        record["requested_size_pixels"] = result.get("requested_size_pixels", "")
                        record["original_output_size"] = result.get("original_output_size", "")
                        record["response_output_size_mismatch"] = bool(result.get("response_output_size_mismatch", False))
                        record["output_size"] = result.get("output_size") or f"{image.width}x{image.height}"
                        ready_images.append(image)
                        save_cached_image(
                            unique_id,
                            item["input_hash"],
                            image,
                            {k: v for k, v in record.items() if k != "image"},
                        )
                    else:
                        record["status"] = "failed"
                        record["error_code"] = result.get("error_code", "ERROR")
                        record["error_reason"] = clip(result.get("error_reason", "Generation failed."))
                        record["raw_error"] = clip(result.get("response") or result.get("explanation") or "")
                    records[position] = record
                    completed_progress += 1
                    _update_progress(pbar, completed_progress, total_progress)

        _update_progress(pbar, total_progress, total_progress)

        target_size = first_image_size(ready_images)
        items: list[dict[str, Any]] = []
        output_images: list[Image.Image] = []
        output_ratio_warnings: list[str] = []
        output_pixel_warnings: list[str] = []
        success = failed = cached = 0

        for position, task in enumerate(valid_tasks, start=1):
            record = records.get(position)
            if record and isinstance(record.get("image"), Image.Image):
                image = record["image"].convert("RGB")
            else:
                reason = record.get("error_code", "") if record else "UNKNOWN"
                image = make_placeholder(target_size, f"task{position} failed", reason)
                if record is None:
                    record = {
                        "index": position,
                        "task_id": task.get("task_id", ""),
                        "name": task.get("name") or f"任务{position}",
                        "prompt": task.get("prompt", ""),
                        "status": "failed",
                        "error_code": "UNKNOWN",
                        "error_reason": "未知错误。",
                    }
            state = record.get("status", "failed")
            if state == "generated":
                success += 1
            elif state == "cached":
                cached += 1
                success += 1
            else:
                failed += 1
            if state in {"generated", "cached"}:
                record.setdefault("output_size", f"{image.width}x{image.height}")
                pixel_mismatch = _pixel_size_mismatch_detail(record, image)
                record["output_size_mismatch"] = bool(pixel_mismatch)
                if pixel_mismatch:
                    output_pixel_warnings.append(pixel_mismatch)
                mismatch = _ratio_mismatch_detail(record, image)
                if mismatch:
                    output_ratio_warnings.append(mismatch)
            output_images.append(image)
            item = dict(record)
            item["image"] = image
            items.append(item)

        images_tensor = batch_tensor(output_images)
        long_pil, long_scaled = long_image(output_images)
        long_tensor = to_tensor(long_pil)

        warnings: list[dict[str, Any]] = []
        if ratio_warnings:
            warnings.append(
                {
                    "code": "RATIO_NORMALIZED",
                    "message": "部分任务的比例不适用于实际平台，已自动回退。",
                    "details": ratio_warnings[:8],
                }
            )
        if long_scaled:
            warnings.append(
                {
                    "code": "LONG_IMAGE_SCALED",
                    "message": "长图像素过大，已自动缩小长图输出。",
                }
            )
        if output_ratio_warnings:
            warnings.append(
                {
                    "code": "OUTPUT_RATIO_MISMATCH",
                    "message": "部分任务输出尺寸和设置比例不一致，请查看 status_json 里的 ratio、api_request_size 和 output_size。",
                    "details": output_ratio_warnings[:8],
                }
            )
        if output_pixel_warnings:
            warnings.append(
                {
                    "code": "OUTPUT_PIXEL_SIZE_MISMATCH",
                    "message": "部分任务的接口实际返回像素尺寸和请求尺寸不一致，节点已保留接口原图，请查看 api_request_size 和 output_size。",
                    "details": output_pixel_warnings[:8],
                }
            )

        bad_keys = key_health.bad_key_records()
        retry_records = key_health.retry_records()

        failed_codes = {
            str(item.get("error_code", ""))
            for item in items
            if item.get("status") == "failed"
        }
        if failed_codes & CONCURRENCY_ERROR_CODES:
            suggested = None
            if actual_concurrency > 4:
                suggested = 4
            elif actual_concurrency > 2:
                suggested = 2
            elif actual_concurrency > 1:
                suggested = 1
            message = "检测到限流、超时或并发限制，建议降低“并发数量”后重试失败任务。"
            if len(api_key_hashes) == 1 and actual_concurrency > 1:
                message = "当前似乎使用 1 个 API Key 同时生成多张图，如频繁失败，建议把并发数量调到 1-2。"
            warning = {
                "code": "CONCURRENCY_LIMIT_SUSPECTED",
                "message": message,
            }
            if suggested:
                warning["suggested_concurrency"] = suggested
            warnings.append(warning)

        status_lines = [
            f"完成 {len(valid_tasks)} 个任务：成功 {success}，缓存 {cached}，失败 {failed}。",
        ]
        for warning in warnings:
            status_lines.append(f"提醒：{warning['message']}")
        if bad_keys:
            status_lines.append("")
            status_lines.append("问题 API Key：")
            for key_record in bad_keys[:12]:
                tasks = ", ".join(str(item) for item in key_record.get("tasks", [])[:8]) or "-"
                status_lines.append(
                    f"- {key_record.get('label', '')}："
                    f"{friendly_error(key_record.get('error_code', 'ERROR'), key_record.get('error_reason', ''))}；"
                    f"本轮已跳过；影响任务：{tasks}"
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
                status_lines.append(f"- {retry.get('task', '')}：{chain} 成功")
            if len(retry_records) > 12:
                status_lines.append(f"- 还有 {len(retry_records) - 12} 条重试记录，详见 status_json。")
        if not valid_tasks:
            status_lines.append("没有有效任务。")

        serializable_items = []
        for item in items:
            clean_item = {k: v for k, v in item.items() if k != "image"}
            serializable_items.append(clean_item)
            state = item.get("status", "failed")
            name = item.get("name") or f"任务{item.get('index', '')}"
            if state == "generated":
                status_lines.append(
                    f"{name}：已生成，用时 {item.get('elapsed', 0.0)} 秒，"
                    f"通道 {item.get('source', '')} #{item.get('api_index', '')}"
                )
            elif state == "cached":
                status_lines.append(f"{name}：已缓存")
            else:
                status_lines.append(
                    f"{name}：生成失败，"
                    f"{friendly_error(item.get('error_code', 'ERROR'), item.get('error_reason', ''))}"
                )

        status_payload = {
            "total": len(valid_tasks),
            "success": success,
            "failed": failed,
            "cached": cached,
            "pending_generated": len(pending),
            "concurrency": actual_concurrency,
            "api_key_count": len(api_key_hashes),
            "bad_keys": bad_keys,
            "retry_records": retry_records,
            "key_failover_count": len(retry_records),
            "warnings": warnings,
            "items": serializable_items,
        }
        results = {
            "type": "lx_image_results",
            "version": 1,
            "items": items,
        }
        status_text = "\n".join(status_lines)
        status_json = json.dumps(status_payload, ensure_ascii=False, indent=2)
        return (images_tensor, long_tensor, results, status_text, status_json)
