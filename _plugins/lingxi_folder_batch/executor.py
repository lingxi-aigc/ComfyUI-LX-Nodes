# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import math
import os
import threading
import time
from collections import deque
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from typing import Any

import comfy.model_management  # type: ignore[reportMissingImports]
import comfy.utils  # type: ignore[reportMissingImports]
import torch
from PIL import Image

from ..categories import LX_RELAY_CATEGORY
from ..lingxi_bridge import lb_http as http_client
from ..lingxi_bridge.lb_image import LingxiBridgeImage
from ..lingxi_bridge.lb_utils import pil2tensor, tensor2pil
from ..lingxi_task_queue.shared import (
    Channel,
    batch_tensor,
    classify_error,
    friendly_error,
    make_placeholder,
    parse_api_channels,
)
from .shared import (
    FOLDER_BATCH_TASKS_TYPE,
    clean_str,
    clip,
    compare_output_path,
    make_saved_compare,
    normalize_tasks,
    payload_meta,
)


MAX_TOTAL_CONCURRENCY = 256
MAX_PER_KEY_CONCURRENCY = 16
DEFAULT_PER_KEY_CONCURRENCY = 4
MAX_TOTAL_CONCURRENCY_WIDGET = "最大总并发"
PER_KEY_CONCURRENCY_WIDGET = "每Key并发"
MAX_PREVIEW = 64
DEFAULT_MAX_UPLOAD_SIDE = 2048
DEFAULT_RETRIES = 1
RETRYABLE_CODES = {"HTTP_429", "RATE_LIMIT", "CONCURRENT_LIMIT", "TIMEOUT", "ERROR"}


def _check_interrupted(cancel_event: threading.Event | None = None) -> None:
    if cancel_event is not None and cancel_event.is_set():
        raise comfy.model_management.InterruptProcessingException()
    comfy.model_management.throw_exception_if_processing_interrupted()


def _sleep_interruptible(seconds: float, cancel_event: threading.Event | None = None) -> None:
    end = time.time() + max(0.0, seconds)
    while True:
        _check_interrupted(cancel_event)
        remaining = end - time.time()
        if remaining <= 0:
            return
        time.sleep(min(0.25, remaining))


def _clamp_int(value: object, default: int, min_value: int, max_value: int) -> int:
    text = clean_str(value)
    try:
        number = int(float(text))
    except (TypeError, ValueError):
        number = default
    return max(min_value, min(max_value, number))


def _parse_max_total_concurrency(value: object) -> int:
    return _clamp_int(value, 0, 0, MAX_TOTAL_CONCURRENCY)


def _is_auto_per_key(value: object) -> bool:
    try:
        return int(float(clean_str(value))) <= 0
    except (TypeError, ValueError):
        return False


def _channel_key(channel: Channel) -> str:
    fingerprint = channel.fingerprint()
    return clean_str(fingerprint.get("api_key_hash")) or f"{channel.source}:{channel.api_index}"


def _resolve_per_key_concurrency(value: object, max_total: int, key_count: int) -> int:
    if _is_auto_per_key(value):
        if max_total > 0 and key_count > 0:
            return max(1, min(MAX_PER_KEY_CONCURRENCY, math.ceil(max_total / key_count)))
        return DEFAULT_PER_KEY_CONCURRENCY
    return _clamp_int(value, DEFAULT_PER_KEY_CONCURRENCY, 1, MAX_PER_KEY_CONCURRENCY)


def _make_concurrency_plan(
    max_total_value: object,
    per_key_value: object,
    pending: list[dict[str, Any]],
) -> dict[str, Any]:
    max_total = _parse_max_total_concurrency(max_total_value)
    key_count = len({_channel_key(item["channel"]) for item in pending if isinstance(item.get("channel"), Channel)})
    per_key = _resolve_per_key_concurrency(per_key_value, max_total, key_count)
    capacity = key_count * per_key
    if not pending or key_count <= 0 or capacity <= 0:
        actual = 0
    elif max_total > 0:
        actual = max(1, min(len(pending), capacity, max_total, MAX_TOTAL_CONCURRENCY))
    else:
        actual = max(1, min(len(pending), capacity, MAX_TOTAL_CONCURRENCY))
    return {
        "max_total": max_total,
        "max_total_label": str(max_total) if max_total > 0 else "自动",
        "requested_per_key": clean_str(per_key_value) or str(DEFAULT_PER_KEY_CONCURRENCY),
        "per_key_auto": _is_auto_per_key(per_key_value),
        "resolved_per_key": per_key,
        "api_key_count": key_count,
        "actual_concurrency": actual,
    }


def _concurrency_progress_extra(plan: dict[str, Any], http_workers: int = 0) -> dict[str, Any]:
    return {
        "max_total_concurrency": plan.get("max_total", 0),
        "max_total_concurrency_label": plan.get("max_total_label", "自动"),
        "requested_per_key_concurrency": plan.get("requested_per_key", str(DEFAULT_PER_KEY_CONCURRENCY)),
        "per_key_concurrency_auto": bool(plan.get("per_key_auto")),
        "resolved_per_key_concurrency": int(plan.get("resolved_per_key", DEFAULT_PER_KEY_CONCURRENCY)),
        "api_key_count": int(plan.get("api_key_count", 0)),
        "http_workers": int(http_workers or 0),
    }


def _update_progress(pbar: Any, done: int, total: int) -> None:
    if pbar is None or total <= 0:
        return
    pbar.update_absolute(min(100, max(0, int(round(done * 100 / total)))))


def _concurrency_status_line(
    actual_concurrency: int,
    api_count: int,
    api_key_count: int,
    pending_count: int,
    max_total_label: str,
    per_key_label: str,
) -> str:
    if actual_concurrency > 0:
        return (
            f"并发：API通道 {api_count} 个，API Key {api_key_count} 个，"
            f"每Key并发 {per_key_label}，总并发 {actual_concurrency}，总上限 {max_total_label}"
        )
    return f"并发：API通道 {api_count} 个，API Key {api_key_count} 个，本次未调用 API"


def _format_duration(seconds: object) -> str:
    try:
        total_seconds = max(0, int(round(float(seconds))))
    except (TypeError, ValueError):
        total_seconds = 0
    hours, remainder = divmod(total_seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


def _final_state(total: int, success: int, failed: int, skipped: int) -> tuple[str, str]:
    if total <= 0:
        return "no_tasks", "无任务"
    if skipped == total and success == 0 and failed == 0:
        return "all_skipped", "全部跳过"
    generated_target = max(0, total - skipped)
    if generated_target > 0 and failed == generated_target and success == 0:
        return "all_failed", "全部失败"
    if failed > 0:
        return "partial_failed", "部分失败"
    return "all_completed", "全部完成"


def _summary_message(state: str, total: int, success: int, failed: int, skipped: int) -> str:
    if state == "all_skipped":
        return f"提示：{skipped} 个任务均因已有结果而跳过。"
    if state == "all_failed":
        return f"提示：需要生成的 {failed} 个任务全部失败，请查看失败任务。"
    if state == "partial_failed":
        return f"提示：有 {failed} 个任务失败，建议查看失败任务和状态JSON。"
    if state == "all_completed" and skipped > 0:
        return f"提示：{success} 个任务已完成，{skipped} 个已有结果已跳过。"
    if state == "all_completed":
        return "提示：全部任务已完成。"
    return "提示：没有可执行任务。"


def _status_title(state: str) -> str:
    if state in {"partial_failed", "all_failed"}:
        return "批量执行完成，但有失败"
    if state == "all_skipped":
        return "批量执行完成，全部跳过"
    if state == "no_tasks":
        return "批量执行完成，无任务"
    return "批量执行完成"


def _progress_payload(
    *,
    started_at: float,
    total: int,
    done: int,
    success: int,
    failed: int,
    skipped: int,
    actual_concurrency: int,
    api_count: int,
    current: str,
    output_root: str,
    state: str,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    elapsed = max(0.0, time.time() - started_at)
    payload: dict[str, Any] = {
        "total": total,
        "done": done,
        "success": success,
        "failed": failed,
        "skipped": skipped,
        "concurrency": actual_concurrency,
        "actual_concurrency": actual_concurrency,
        "api_channel_count": api_count,
        "current": current,
        "output_root": output_root,
        "state": state,
        "started_at": started_at,
        "elapsed_seconds": round(elapsed, 3),
        "elapsed_text": _format_duration(elapsed),
    }
    if state == "running" and 0 < done < total:
        remaining = elapsed / max(1, done) * max(0, total - done)
        payload["remaining_seconds"] = round(remaining, 3)
        payload["remaining_text"] = _format_duration(remaining)
    elif state in {"done", "cancelled"}:
        payload["remaining_seconds"] = 0
        payload["remaining_text"] = "00:00:00"
    if extra:
        payload.update(extra)
    return payload


def _load_reference_image(path: str, max_side: int) -> torch.Tensor:
    with Image.open(path) as image:
        pil = image.convert("RGB")
    if max_side > 0:
        width, height = pil.size
        longest = max(width, height)
        if longest > max_side:
            scale = max_side / longest
            next_size = (max(1, int(round(width * scale))), max(1, int(round(height * scale))))
            pil = pil.resize(next_size, Image.LANCZOS)
    return pil2tensor(pil)


def _save_image(image: Image.Image, path: str, save_format: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fmt = clean_str(save_format).upper()
    if fmt in {"JPG", "JPEG"}:
        image.convert("RGB").save(path, format="JPEG", quality=95)
    elif fmt == "WEBP":
        image.convert("RGB").save(path, format="WEBP", quality=95)
    else:
        image.convert("RGB").save(path, format="PNG")


def _task_image_paths(task: dict[str, Any]) -> list[str]:
    raw = task.get("image_paths", [])
    if not isinstance(raw, list):
        return []
    return [clean_str(item) for item in raw if clean_str(item)]


def _call_once(
    task: dict[str, Any],
    channel: Channel,
    max_upload_side: int,
    cancel_event: threading.Event | None = None,
) -> dict[str, Any]:
    started = time.time()
    try:
        _check_interrupted(cancel_event)
        image_paths = _task_image_paths(task)
        kwargs = {}
        for index, path in enumerate(image_paths, start=1):
            _check_interrupted(cancel_event)
            kwargs[f"image{index}"] = _load_reference_image(path, max_upload_side)
        node = LingxiBridgeImage()
        node._cancel_event = cancel_event
        image_tensor, response, image_url, explanation = node.generate_image(
            prompt=task.get("prompt", ""),
            ratio=task.get("ratio", "auto"),
            size=task.get("size", "2K"),
            quality=task.get("quality", "medium"),
            format="jpeg",
            moderation=task.get("moderation", "low"),
            seed=0,
            info=channel.to_info_json(),
            **kwargs,
        )
        _check_interrupted(cancel_event)
        elapsed = time.time() - started
        if isinstance(image_tensor, torch.Tensor):
            pil = tensor2pil(image_tensor)[0].convert("RGB")
            return {
                "status": "generated",
                "image": pil,
                "response": response,
                "url": image_url,
                "explanation": explanation,
                "elapsed": elapsed,
            }
        code, reason = classify_error(response, explanation)
        return {
            "status": "failed",
            "error_code": code,
            "error_reason": reason,
            "response": response,
            "explanation": explanation,
            "elapsed": elapsed,
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
        }


def _call_with_retry(
    task: dict[str, Any],
    channel: Channel,
    max_upload_side: int,
    cancel_event: threading.Event | None = None,
) -> dict[str, Any]:
    attempts: list[dict[str, Any]] = []
    for attempt in range(DEFAULT_RETRIES + 1):
        _check_interrupted(cancel_event)
        result = _call_once(task, channel, max_upload_side, cancel_event)
        result["attempt"] = attempt + 1
        attempts.append({key: value for key, value in result.items() if key != "image"})
        if result.get("status") == "generated":
            result["attempts"] = attempts
            return result
        code = clean_str(result.get("error_code", "ERROR"))
        if attempt >= DEFAULT_RETRIES or code not in RETRYABLE_CODES:
            result["attempts"] = attempts
            return result
        _sleep_interruptible(1.5 * (attempt + 1), cancel_event)
    result = attempts[-1] if attempts else {"status": "failed", "error_code": "ERROR", "error_reason": "unknown"}
    result["attempts"] = attempts
    return result


def _send_progress(unique_id: object, payload: dict[str, Any]) -> None:
    node_id = clean_str(unique_id)
    if not node_id:
        return
    try:
        from server import PromptServer  # type: ignore[reportMissingImports]

        PromptServer.instance.send_sync(
            "lx_folder_batch_progress",
            {"node": node_id, **payload},
        )
    except Exception:
        pass


def _send_cancelled_progress(
    unique_id: object,
    *,
    started_at: float,
    total: int,
    done: int,
    success: int,
    failed: int,
    skipped: int,
    actual_concurrency: int,
    api_count: int,
    output_root: str,
    extra: dict[str, Any] | None = None,
) -> None:
    payload_extra = {
        **(extra or {}),
        "state_label": "已取消",
        "message": "用户已取消批量执行。",
    }
    _send_progress(
        unique_id,
        _progress_payload(
            started_at=started_at,
            total=total,
            done=done,
            success=success,
            failed=failed,
            skipped=skipped,
            actual_concurrency=actual_concurrency,
            api_count=api_count,
            current="已取消",
            output_root=output_root,
            state="cancelled",
            extra=payload_extra,
        ),
    )


def _save_compare_image(task: dict[str, Any], result_image: Image.Image, output_root: str) -> dict[str, Any]:
    compare_path = compare_output_path(output_root, clean_str(task.get("output_rel_path")))
    collage = make_saved_compare(_task_image_paths(task), result_image=result_image)
    os.makedirs(os.path.dirname(compare_path), exist_ok=True)
    collage.save(compare_path, format="PNG")
    return {"compare_path": compare_path}


class LingxiFolderBatchExecuteSave:
    CATEGORY = f"{LX_RELAY_CATEGORY}/文件夹批量"
    RETURN_TYPES = ("IMAGE", "STRING", "STRING")
    RETURN_NAMES = ("预览图像", "状态文本", "状态JSON")
    FUNCTION = "execute"
    SIZE = (440, 320)
    SEARCH_ALIASES = ("lx", "LX", "灵犀", "灵犀批量执行（文件夹）", "灵犀批量执行保存", "批量执行保存", "文件夹API批量")

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "批量任务": (FOLDER_BATCH_TASKS_TYPE, {"tooltip": "连接“灵犀单图批量”或“灵犀多图批量”输出的任务包。这里不重新扫描文件夹。"}),
                "API池": ("STRING", {"default": "", "forceInput": True, "tooltip": "连接灵犀 API 池或合并后的 API 池。多个 API 通道会按任务顺序轮流分配。"}),
                MAX_TOTAL_CONCURRENCY_WIDGET: ("INT", {"default": 0, "min": 0, "max": MAX_TOTAL_CONCURRENCY, "step": 1, "tooltip": "0 表示自动：按 API Key 数量和每Key并发自动计算；1-256 作为本次任务的总并发上限。"}),
                PER_KEY_CONCURRENCY_WIDGET: ("INT", {"default": 0, "min": 0, "max": MAX_PER_KEY_CONCURRENCY, "step": 1, "tooltip": "0 表示自动：有最大总并发时按 Key 均分，否则使用 4；1-16 作为单个 API Key 同时处理的任务数。"}),
                "已有结果处理": ("BOOLEAN", {"default": False, "label_on": "覆盖", "label_off": "跳过", "tooltip": "跳过：输出文件已存在就不重新生成；覆盖：即使已有文件也会重新生成并写回同一路径。"}),
                "上传图最长边(px)": ("INT", {"default": DEFAULT_MAX_UPLOAD_SIDE, "min": 0, "max": 8192, "step": 64, "tooltip": "上传前会把输入参考图按最长边等比缩小。0 表示不缩放；数值越小上传越快，但细节会减少。"}),
                "保存对比图": ("BOOLEAN", {"default": False, "label_on": "保存", "label_off": "关闭", "tooltip": "开启后仅额外保存输入图与结果图的对比图，方便检查批量结果。"}),
                "显示实时进度": ("BOOLEAN", {"default": False, "label_on": "显示", "label_off": "关闭", "tooltip": "在节点下方显示实时进度面板。只影响界面显示，不影响执行速度或输出。"}),
            },
            "hidden": {
                "unique_id": "UNIQUE_ID",
            }
        }

    @classmethod
    def VALIDATE_INPUTS(cls, **kwargs):
        return True

    @classmethod
    def IS_CHANGED(cls, **kwargs):
        return time.time()

    def _select_channels(self, tasks: list[dict[str, Any]], api_pool: object) -> tuple[dict[int, Channel | None], int]:
        channels = parse_api_channels(api_pool, "folder_batch")
        result: dict[int, Channel | None] = {}
        if not channels:
            for index in range(1, len(tasks) + 1):
                result[index] = None
            return result, 0
        for index, _task in enumerate(tasks, start=1):
            result[index] = channels[(index - 1) % len(channels)]
        return result, len(channels)

    def execute(
        self,
        批量任务,
        API池="",
        已有结果处理=False,
        保存对比图=False,
        显示实时进度=False,
        unique_id=None,
        **kwargs,
    ):
        最大总并发 = kwargs.get(MAX_TOTAL_CONCURRENCY_WIDGET, 0)
        每Key并发 = kwargs.get(PER_KEY_CONCURRENCY_WIDGET, 0)
        上传图最长边 = kwargs.get("上传图最长边(px)", DEFAULT_MAX_UPLOAD_SIDE)

        started_at = time.time()
        cancel_event = threading.Event()
        progress_extra: dict[str, Any] = {}
        actual_concurrency = 0
        api_count = 0
        completed = 0
        success = failed = skipped = 0
        total = 0
        output_root = ""
        tasks = normalize_tasks(批量任务)
        meta = payload_meta(批量任务)
        output_root = clean_str(meta.get("output_root"))
        if not output_root:
            for task in tasks:
                output_root = clean_str(task.get("output_root"))
                if output_root:
                    break
        if output_root:
            os.makedirs(output_root, exist_ok=True)

        total = len(tasks)
        preview_limit = min(total, MAX_PREVIEW)
        max_upload_side = _clamp_int(上传图最长边, DEFAULT_MAX_UPLOAD_SIDE, 0, 8192)
        channels, api_count = self._select_channels(tasks, API池)
        available_api_key_count = len({
            _channel_key(channel)
            for channel in channels.values()
            if isinstance(channel, Channel)
        })

        records: list[dict[str, Any]] = []
        pending: list[dict[str, Any]] = []
        preview_slots: list[Image.Image | None] = [None] * preview_limit

        pbar = comfy.utils.ProgressBar(100) if total else None
        _update_progress(pbar, completed, total)
        _send_progress(
            unique_id,
            _progress_payload(
                started_at=started_at,
                total=total,
                done=completed,
                success=success,
                failed=failed,
                skipped=skipped,
                actual_concurrency=0,
                api_count=api_count,
                current="准备任务",
                output_root=output_root,
                state="running",
                extra={"api_key_count": available_api_key_count},
            ),
        )

        for position, task in enumerate(tasks, start=1):
            _check_interrupted(cancel_event)
            output_path = clean_str(task.get("output_path"))
            record_base = {
                "index": position,
                "task_id": task.get("task_id", ""),
                "name": task.get("name", f"任务{position}"),
                "image_rel_paths": task.get("image_rel_paths", []),
                "output_path": output_path,
                "output_rel_path": task.get("output_rel_path", ""),
            }
            if not output_path:
                failed += 1
                records.append({**record_base, "status": "failed", "error_code": "NO_OUTPUT", "error_reason": "输出路径为空"})
                completed += 1
                _update_progress(pbar, completed, total)
                _send_progress(
                    unique_id,
                    _progress_payload(
                        started_at=started_at,
                        total=total,
                        done=completed,
                        success=success,
                        failed=failed,
                        skipped=skipped,
                        actual_concurrency=0,
                        api_count=api_count,
                        current=record_base.get("name", f"任务{position}"),
                        output_root=output_root,
                        state="running",
                        extra={"api_key_count": available_api_key_count},
                    ),
                )
                continue
            if not 已有结果处理 and os.path.isfile(output_path):
                skipped += 1
                record = {**record_base, "status": "skipped", "reason": "output_exists"}
                if 保存对比图 and output_root:
                    try:
                        existing_image = Image.open(output_path).convert("RGB")
                        record.update(_save_compare_image(task, existing_image, output_root))
                    except Exception as exc:
                        record["compare_error"] = clip(exc, 300)
                records.append(record)
                if position <= preview_limit:
                    try:
                        preview_slots[position - 1] = Image.open(output_path).convert("RGB")
                    except Exception:
                        pass
                completed += 1
                _update_progress(pbar, completed, total)
                _send_progress(
                    unique_id,
                    _progress_payload(
                        started_at=started_at,
                        total=total,
                        done=completed,
                        success=success,
                        failed=failed,
                        skipped=skipped,
                        actual_concurrency=0,
                        api_count=api_count,
                        current=record_base.get("output_rel_path") or record_base.get("name"),
                        output_root=output_root,
                        state="running",
                        extra={"api_key_count": available_api_key_count},
                    ),
                )
                continue
            channel = channels.get(position)
            if channel is None:
                failed += 1
                records.append({**record_base, "status": "failed", "error_code": "NO_API", "error_reason": "没有可用 API 配置"})
                completed += 1
                _update_progress(pbar, completed, total)
                _send_progress(
                    unique_id,
                    _progress_payload(
                        started_at=started_at,
                        total=total,
                        done=completed,
                        success=success,
                        failed=failed,
                        skipped=skipped,
                        actual_concurrency=0,
                        api_count=api_count,
                        current=record_base.get("output_rel_path") or record_base.get("name"),
                        output_root=output_root,
                        state="running",
                        extra={"api_key_count": available_api_key_count},
                    ),
                )
                continue
            pending.append({"position": position, "task": task, "channel": channel, "record_base": record_base})

        concurrency_plan = _make_concurrency_plan(最大总并发, 每Key并发, pending)
        actual_concurrency = int(concurrency_plan["actual_concurrency"])
        resolved_per_key = int(concurrency_plan["resolved_per_key"])
        http_workers = http_client.configure_executor_for_concurrency(actual_concurrency) if actual_concurrency else 0
        progress_extra = _concurrency_progress_extra(concurrency_plan, http_workers)
        api_key_count = available_api_key_count or int(concurrency_plan["api_key_count"])
        progress_extra["api_key_count"] = api_key_count
        max_total_label = str(concurrency_plan["max_total_label"])
        per_key_label = "0=自动" if concurrency_plan["per_key_auto"] else str(resolved_per_key)
        if pending:
            _send_progress(
                unique_id,
                _progress_payload(
                    started_at=started_at,
                    total=total,
                    done=completed,
                    success=success,
                    failed=failed,
                    skipped=skipped,
                    actual_concurrency=actual_concurrency,
                    api_count=api_count,
                    current=f"开始执行 {len(pending)} 个任务",
                    output_root=output_root,
                    state="running",
                    extra=progress_extra,
                ),
            )
        if pending and actual_concurrency > 0:
            queues_by_key: dict[str, deque[dict[str, Any]]] = {}
            key_order: list[str] = []
            for item in pending:
                key = _channel_key(item["channel"])
                item["api_key_hash"] = key
                if key not in queues_by_key:
                    queues_by_key[key] = deque()
                    key_order.append(key)
                queues_by_key[key].append(item)
            in_flight_by_key = {key: 0 for key in key_order}
            next_key_index = 0

            executor = ThreadPoolExecutor(max_workers=actual_concurrency, thread_name_prefix="LingxiFolderBatch")
            future_map: dict[Any, dict[str, Any]] = {}
            executor_shutdown = False

            try:
                def submit_next() -> bool:
                    nonlocal next_key_index
                    _check_interrupted(cancel_event)
                    if len(future_map) >= actual_concurrency or not key_order:
                        return False
                    for _ in range(len(key_order)):
                        _check_interrupted(cancel_event)
                        key = key_order[next_key_index % len(key_order)]
                        next_key_index += 1
                        if not queues_by_key[key] or in_flight_by_key[key] >= resolved_per_key:
                            continue
                        item = queues_by_key[key].popleft()
                        future = executor.submit(_call_with_retry, item["task"], item["channel"], max_upload_side, cancel_event)
                        future_map[future] = item
                        in_flight_by_key[key] += 1
                        return True
                    return False

                def fill_slots() -> None:
                    while len(future_map) < actual_concurrency:
                        _check_interrupted(cancel_event)
                        if not submit_next():
                            break

                fill_slots()
                while future_map:
                    done_futures, _pending_futures = wait(future_map, timeout=0.25, return_when=FIRST_COMPLETED)
                    if not done_futures:
                        _check_interrupted(cancel_event)
                        continue
                    _check_interrupted(cancel_event)
                    for future in done_futures:
                        item = future_map.pop(future)
                        key = item.get("api_key_hash", "")
                        if key in in_flight_by_key:
                            in_flight_by_key[key] = max(0, in_flight_by_key[key] - 1)
                        task = item["task"]
                        channel = item["channel"]
                        record_base = item["record_base"]
                        try:
                            result = future.result()
                        except comfy.model_management.InterruptProcessingException:
                            cancel_event.set()
                            raise
                        except Exception as exc:
                            code, reason = classify_error(str(exc), "")
                            result = {
                                "status": "failed",
                                "error_code": code,
                                "error_reason": reason,
                                "elapsed": 0.0,
                                "attempts": [{"status": "failed", "error_code": code, "error_reason": reason}],
                            }

                        _check_interrupted(cancel_event)
                        record = {
                            **record_base,
                            "status": result.get("status", "failed"),
                            "elapsed": round(float(result.get("elapsed", 0.0)), 3),
                            "attempt": result.get("attempt", 1),
                            "attempts": result.get("attempts", []),
                            "api_key_hash": item.get("api_key_hash", ""),
                            **channel.public_status(),
                        }
                        if result.get("status") == "generated" and isinstance(result.get("image"), Image.Image):
                            image = result["image"].convert("RGB")
                            try:
                                _check_interrupted(cancel_event)
                                _save_image(image, task.get("output_path", ""), task.get("save_format", "PNG"))
                                success += 1
                                record["status"] = "generated"
                                record["output_size"] = f"{image.width}x{image.height}"
                                if result.get("url"):
                                    record["url"] = result.get("url")
                                if 保存对比图 and output_root:
                                    try:
                                        _check_interrupted(cancel_event)
                                        record.update(_save_compare_image(task, image, output_root))
                                    except Exception as exc:
                                        record["compare_error"] = clip(exc, 300)
                                position = int(item.get("position", 0) or 0)
                                if 1 <= position <= preview_limit:
                                    preview_slots[position - 1] = image
                            except comfy.model_management.InterruptProcessingException:
                                cancel_event.set()
                                raise
                            except Exception as exc:
                                failed += 1
                                code, reason = classify_error(str(exc), "")
                                record["status"] = "failed"
                                record["error_code"] = code
                                record["error_reason"] = reason
                        else:
                            failed += 1
                            error_code = result.get("error_code", "ERROR")
                            error_reason = clip(result.get("error_reason", "生成失败。"), 800)
                            record["status"] = "failed"
                            record["error_code"] = error_code
                            record["error_reason"] = error_reason
                            record["friendly_error"] = friendly_error(error_code, error_reason)
                            raw_error = clip(result.get("response") or result.get("explanation") or "", 1200)
                            if raw_error:
                                record["raw_error"] = raw_error
                        records.append(record)
                        completed += 1
                        _update_progress(pbar, completed, total)
                        _send_progress(
                            unique_id,
                            _progress_payload(
                                started_at=started_at,
                                total=total,
                                done=completed,
                                success=success,
                                failed=failed,
                                skipped=skipped,
                                actual_concurrency=actual_concurrency,
                                api_count=api_count,
                                current=record.get("output_rel_path") or record.get("name"),
                                output_root=output_root,
                                state="running",
                                extra=progress_extra,
                            ),
                        )
                        fill_slots()
            except comfy.model_management.InterruptProcessingException:
                cancel_event.set()
                for future in list(future_map):
                    future.cancel()
                try:
                    http_client.close_all_sessions()
                except Exception:
                    pass
                executor.shutdown(wait=False, cancel_futures=True)
                executor_shutdown = True
                _send_cancelled_progress(
                    unique_id,
                    started_at=started_at,
                    total=total,
                    done=completed,
                    success=success,
                    failed=failed,
                    skipped=skipped,
                    actual_concurrency=actual_concurrency,
                    api_count=api_count,
                    output_root=output_root,
                    extra=progress_extra,
                )
                raise
            finally:
                if not executor_shutdown:
                    executor.shutdown(wait=not cancel_event.is_set(), cancel_futures=cancel_event.is_set())

        _update_progress(pbar, total, total)

        records.sort(key=lambda item: int(item.get("index", 0)))

        preview_images = [image for image in preview_slots if image is not None]
        if not preview_images:
            preview_images = [make_placeholder((1024, 1024), "no preview", "no generated or existing image")]
        preview_batch = batch_tensor(preview_images)

        warnings: list[str] = []
        if resolved_per_key > 8:
            warnings.append("当前每Key并发较高，如遇限流或超时建议降低每Key并发。")
        if actual_concurrency > 64:
            warnings.append("当前实际并发较高，如出现网络拥堵或保存变慢，建议设置最大总并发。")

        elapsed_seconds = max(0.0, time.time() - started_at)
        api_elapsed_seconds = round(
            sum(float(item.get("elapsed", 0.0) or 0.0) for item in records),
            3,
        )
        timed_items = sum(1 for item in records if float(item.get("elapsed", 0.0) or 0.0) > 0)
        api_average_seconds = round(api_elapsed_seconds / timed_items, 3) if timed_items else 0.0
        batch_average_seconds = round(elapsed_seconds / total, 3) if total else 0.0
        state, state_label = _final_state(total, success, failed, skipped)
        message = _summary_message(state, total, success, failed, skipped)
        summary = {
            "state": state,
            "state_label": state_label,
            "total": total,
            "success": success,
            "failed": failed,
            "skipped": skipped,
            "pending_generated": len(pending),
            "requested_max_total_concurrency": clean_str(最大总并发) or "0=自动",
            "max_total_concurrency": int(concurrency_plan["max_total"]),
            "max_total_concurrency_label": max_total_label,
            "requested_per_key_concurrency": clean_str(每Key并发) or str(DEFAULT_PER_KEY_CONCURRENCY),
            "per_key_concurrency_auto": bool(concurrency_plan["per_key_auto"]),
            "resolved_per_key_concurrency": resolved_per_key,
            "actual_concurrency": actual_concurrency,
            "api_channel_count": api_count,
            "api_key_count": api_key_count,
            "http_workers": http_workers,
            "elapsed_seconds": round(elapsed_seconds, 3),
            "elapsed_text": _format_duration(elapsed_seconds),
            "api_elapsed_seconds": api_elapsed_seconds,
            "api_average_seconds": api_average_seconds,
            "api_average_text": f"{api_average_seconds:.1f} 秒/张" if api_average_seconds > 0 else "0 秒/张",
            "batch_average_seconds": batch_average_seconds,
            "batch_average_text": f"{batch_average_seconds:.1f} 秒/张" if batch_average_seconds > 0 else "0 秒/张",
            "average_seconds": batch_average_seconds,
            "average_text": f"{batch_average_seconds:.1f} 秒/张" if batch_average_seconds > 0 else "0 秒/张",
            "message": message,
        }

        status_lines = [
            _status_title(state),
            f"任务：{total} 个",
            f"进度：{total} / {total}",
            f"结果：成功 {success}，失败 {failed}，跳过 {skipped}",
            _concurrency_status_line(
                actual_concurrency,
                api_count,
                api_key_count,
                len(pending),
                max_total_label,
                per_key_label,
            ),
            f"耗时：{summary['elapsed_text']}，平均 {summary['average_text']}",
        ]
        if output_root:
            status_lines.append(f"输出：{output_root}")
        status_lines.append("")
        status_lines.append(message)
        for warning in warnings:
            status_lines.append(f"提醒：{warning}")
        failed_items = [item for item in records if item.get("status") == "failed"]
        if failed_items:
            status_lines.append("")
            status_lines.append("失败任务：")
            for item in failed_items[:12]:
                status_lines.append(
                    f"- {item.get('index')}. {item.get('output_rel_path') or item.get('name')}: "
                    f"{friendly_error(item.get('error_code', 'ERROR'), item.get('error_reason', ''))}"
                )
            if len(failed_items) > 12:
                status_lines.append(f"... 还有 {len(failed_items) - 12} 个失败任务")

        status_payload = {
            "type": "lx_folder_batch_execute_status",
            "version": 2,
            "summary": summary,
            "total": total,
            "success": success,
            "failed": failed,
            "skipped": skipped,
            "pending_generated": len(pending),
            "requested_max_total_concurrency": clean_str(最大总并发) or "0=自动",
            "max_total_concurrency": int(concurrency_plan["max_total"]),
            "max_total_concurrency_label": max_total_label,
            "requested_per_key_concurrency": clean_str(每Key并发) or str(DEFAULT_PER_KEY_CONCURRENCY),
            "per_key_concurrency_auto": bool(concurrency_plan["per_key_auto"]),
            "resolved_per_key_concurrency": resolved_per_key,
            "actual_concurrency": actual_concurrency,
            "concurrency": actual_concurrency,
            "api_channel_count": api_count,
            "api_key_count": api_key_count,
            "http_workers": http_workers,
            "output_root": output_root,
            "max_upload_side": max_upload_side,
            "save_compare": bool(保存对比图),
            "warnings": warnings,
            "items": records,
        }
        status_json = json.dumps(status_payload, ensure_ascii=False, indent=2)

        _send_progress(
            unique_id,
            _progress_payload(
                started_at=started_at,
                total=total,
                done=total,
                success=success,
                failed=failed,
                skipped=skipped,
                actual_concurrency=actual_concurrency,
                api_count=api_count,
                current=state_label,
                output_root=output_root,
                state="done",
                extra={
                    **progress_extra,
                    "summary": summary,
                    "state_label": state_label,
                    "message": message,
                    "api_elapsed_seconds": api_elapsed_seconds,
                    "api_average_seconds": api_average_seconds,
                    "api_average_text": summary["api_average_text"],
                    "batch_average_seconds": batch_average_seconds,
                    "batch_average_text": summary["batch_average_text"],
                    "average_seconds": batch_average_seconds,
                    "average_text": summary["average_text"],
                },
            ),
        )

        return (
            preview_batch,
            "\n".join(status_lines),
            status_json,
        )
