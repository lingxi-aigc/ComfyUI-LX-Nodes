# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import os
import time
from typing import Any

from ..categories import LX_RELAY_CATEGORY
from .lb_cache_paths import get_cache_dir, get_cache_root


MODE_OPTIONS = ["仅扫描", "清理"]
SCOPE_OPTIONS = ["全部缓存", "任务队列", "旧版批量", "局部编辑"]
DAYS_OPTIONS = ["0=清空所选缓存", "1", "3", "7", "14", "30", "90"]
DETAIL_LIMIT = 12


def _cache_targets() -> list[dict[str, Any]]:
    return [
        {
            "id": "task_queue",
            "scope": "任务队列",
            "name": "任务队列缓存",
            "path": get_cache_dir("task_queue"),
            "pair_mode": "same_base",
        },
        {
            "id": "concurrent",
            "scope": "旧版批量",
            "name": "旧版批量缓存",
            "path": get_cache_dir("concurrent_bridge"),
            "pair_mode": "same_base",
        },
        {
            "id": "inpaint",
            "scope": "局部编辑",
            "name": "局部编辑缓存",
            "path": get_cache_dir("inpaint_api"),
            "pair_mode": "raw_suffix",
        },
    ]


def _clean_str(value: object) -> str:
    return "" if value is None else str(value).strip()


def _format_bytes(size: object) -> str:
    try:
        value = max(0, float(size))
    except (TypeError, ValueError):
        value = 0.0
    units = ["B", "KB", "MB", "GB", "TB"]
    unit = 0
    while value >= 1024 and unit < len(units) - 1:
        value /= 1024
        unit += 1
    if unit == 0:
        return f"{int(value)} {units[unit]}"
    return f"{value:.1f} {units[unit]}"


def _parse_days(value: object) -> int:
    text = _clean_str(value)
    if not text or text.startswith("0"):
        return 0
    try:
        return max(0, int(float(text)))
    except (TypeError, ValueError):
        return 0


def _safe_stat(path: str) -> os.stat_result | None:
    try:
        return os.stat(path)
    except OSError:
        return None


def _is_under(path: str, root: str) -> bool:
    try:
        real_path = os.path.realpath(path)
        real_root = os.path.realpath(root)
        return real_path == real_root or real_path.startswith(real_root + os.sep)
    except OSError:
        return False


def _expected_pair(path: str, pair_mode: str) -> str:
    base, ext = os.path.splitext(path)
    ext = ext.lower()
    if pair_mode == "raw_suffix":
        if ext == ".json":
            return base + "_raw.png"
        if path.lower().endswith("_raw.png"):
            return path[: -len("_raw.png")] + ".json"
        return ""
    if ext == ".json":
        return base + ".png"
    if ext == ".png":
        return base + ".json"
    return ""


def _scan_target(target: dict[str, Any], now: float, keep_days: int, clean_orphans: bool) -> dict[str, Any]:
    root = os.path.realpath(target["path"])
    records: list[dict[str, Any]] = []
    if os.path.isdir(root):
        for current, dirs, files in os.walk(root):
            dirs[:] = [name for name in dirs if not name.startswith(".")]
            for name in files:
                if name.startswith("."):
                    continue
                path = os.path.join(current, name)
                if not _is_under(path, root):
                    continue
                stat = _safe_stat(path)
                if stat is None or not os.path.isfile(path):
                    continue
                pair_path = _expected_pair(path, target["pair_mode"])
                orphan = bool(pair_path) and not os.path.isfile(pair_path)
                mtime = float(stat.st_mtime)
                records.append(
                    {
                        "path": path,
                        "relative_path": os.path.relpath(path, root),
                        "size": int(stat.st_size),
                        "size_text": _format_bytes(stat.st_size),
                        "mtime": mtime,
                        "age_days": round(max(0.0, (now - mtime) / 86400), 2),
                        "orphan": orphan,
                        "reason": "",
                    }
                )

    selected: dict[str, dict[str, Any]] = {}
    cutoff = now - keep_days * 86400 if keep_days > 0 else None
    for record in records:
        reason = ""
        if keep_days == 0:
            reason = "清空所选缓存"
        elif clean_orphans and record["orphan"]:
            reason = "孤儿文件"
        elif cutoff is not None and float(record["mtime"]) < cutoff:
            reason = f"超过 {keep_days} 天未使用"
        if reason:
            selected[record["path"]] = {**record, "reason": reason}

    cleanable = list(selected.values())
    total_bytes = sum(int(record["size"]) for record in records)
    return {
        "id": target["id"],
        "name": target["name"],
        "path": root,
        "exists": os.path.isdir(root),
        "file_count": len(records),
        "bytes": total_bytes,
        "bytes_text": _format_bytes(total_bytes),
        "cleanable_count": len(cleanable),
        "cleanable_bytes": sum(int(record["size"]) for record in cleanable),
        "cleanable_text": _format_bytes(sum(int(record["size"]) for record in cleanable)),
        "oldest_mtime": min((float(record["mtime"]) for record in records), default=None),
        "newest_mtime": max((float(record["mtime"]) for record in records), default=None),
        "records": records,
        "cleanable": cleanable,
    }


def _selected_targets(scope: str) -> list[dict[str, Any]]:
    targets = _cache_targets()
    if scope == "全部缓存":
        return targets
    return [target for target in targets if target["scope"] == scope]


def _delete_records(targets: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], int]:
    deleted: list[dict[str, Any]] = []
    failed: list[dict[str, Any]] = []
    deleted_bytes = 0
    allowed_roots = {target["id"]: target["path"] for target in targets}
    for target in targets:
        root = allowed_roots[target["id"]]
        for record in target["cleanable"]:
            path = record["path"]
            if not _is_under(path, root):
                failed.append({**record, "error": "路径不在允许的缓存目录内"})
                continue
            try:
                if os.path.isfile(path):
                    size = int(record.get("size", 0))
                    os.remove(path)
                    deleted_bytes += size
                    deleted.append({**record, "target": target["name"]})
            except OSError as exc:
                failed.append({**record, "target": target["name"], "error": str(exc)})
    return deleted, failed, deleted_bytes


def _remove_empty_dirs(targets: list[dict[str, Any]]) -> tuple[int, list[dict[str, str]]]:
    removed = 0
    failed: list[dict[str, str]] = []
    for target in targets:
        root = target["path"]
        if not os.path.isdir(root):
            continue
        for current, dirs, files in os.walk(root, topdown=False):
            if os.path.realpath(current) == os.path.realpath(root):
                continue
            if dirs or files:
                continue
            if not _is_under(current, root):
                continue
            try:
                os.rmdir(current)
                removed += 1
            except OSError as exc:
                failed.append({"path": current, "error": str(exc)})
    return removed, failed


def _target_summary_lines(targets: list[dict[str, Any]], detail_limit: int) -> list[str]:
    lines: list[str] = []
    for target in targets:
        lines.extend(
            [
                "",
                f"{target['name']}：",
                f"路径：{target['path']}",
                f"占用：{target['bytes_text']}，文件 {target['file_count']} 个",
                f"可清理：{target['cleanable_text']}，文件 {target['cleanable_count']} 个",
            ]
        )
        if detail_limit > 0 and target["cleanable"]:
            lines.append(f"可清理明细（前 {min(detail_limit, len(target['cleanable']))} 条）：")
            for record in target["cleanable"][:detail_limit]:
                lines.append(f"- {record['relative_path']} / {record['size_text']} / {record['reason']}")
    return lines


class LingxiCacheManager:
    CATEGORY = f"{LX_RELAY_CATEGORY}/帮助与维护"
    RETURN_TYPES = ("STRING", "STRING")
    RETURN_NAMES = ("状态文本", "状态JSON")
    FUNCTION = "manage"
    SIZE = (460, 360)
    SEARCH_ALIASES = ("lx", "LX", "灵犀", "缓存管理", "缓存清理", "清理缓存", "cache cleanup")

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "操作模式": (MODE_OPTIONS, {"default": "仅扫描", "tooltip": "仅扫描不会删除任何文件；清理模式也必须打开确认清理才会删除。"}),
                "清理范围": (SCOPE_OPTIONS, {"default": "全部缓存", "tooltip": "只管理 LX-Relay 新的集中缓存目录，不会清理 output 或用户图片。"}),
                "保留最近天数": (DAYS_OPTIONS, {"default": "7", "tooltip": "清理超过这个天数未使用的缓存；0 表示清空所选范围。"}),
                "确认清理": ("BOOLEAN", {"default": False, "label_on": "确认", "label_off": "未确认", "tooltip": "只有操作模式为清理且这里为确认时，才会真正删除文件。"}),
            }
        }

    @classmethod
    def VALIDATE_INPUTS(cls, **kwargs):
        return True

    @classmethod
    def IS_CHANGED(cls, **kwargs):
        return time.time()

    def manage(
        self,
        操作模式="仅扫描",
        清理范围="全部缓存",
        保留最近天数="7",
        确认清理=False,
    ):
        now = time.time()
        mode = _clean_str(操作模式) or "仅扫描"
        scope = _clean_str(清理范围) or "全部缓存"
        keep_days = _parse_days(保留最近天数)
        detail_limit = DETAIL_LIMIT
        selected = _selected_targets(scope)
        targets = [
            _scan_target(target, now, keep_days, True)
            for target in selected
        ]

        cleanable_bytes = sum(int(target["cleanable_bytes"]) for target in targets)
        cleanable_count = sum(int(target["cleanable_count"]) for target in targets)
        deleted: list[dict[str, Any]] = []
        failed: list[dict[str, Any]] = []
        empty_dir_failed: list[dict[str, str]] = []
        deleted_bytes = 0
        removed_empty_dirs = 0
        confirmed = bool(确认清理)
        did_delete = mode == "清理" and confirmed
        blocked_by_confirmation = mode == "清理" and not confirmed

        if did_delete:
            deleted, failed, deleted_bytes = _delete_records(targets)
            removed_empty_dirs, empty_dir_failed = _remove_empty_dirs(targets)

        title = "缓存清理完成" if did_delete else "缓存扫描完成，未删除任何文件"
        lines = [
            title,
            "",
            f"缓存根目录：{get_cache_root()}",
            f"范围：{scope}",
            f"模式：{mode}",
            f"规则：保留最近 {keep_days} 天，自动清理孤儿文件" if keep_days > 0 else "规则：清空所选范围，自动清理孤儿文件",
            "",
            f"总占用：{_format_bytes(sum(int(target['bytes']) for target in targets))}，文件 {sum(int(target['file_count']) for target in targets)} 个",
            f"预计可清理：{_format_bytes(cleanable_bytes)}，文件 {cleanable_count} 个",
        ]
        if did_delete:
            lines.extend(
                [
                    "",
                    f"释放空间：{_format_bytes(deleted_bytes)}",
                    f"删除文件：{len(deleted)} 个",
                    f"删除空目录：{removed_empty_dirs} 个",
                    f"失败：{len(failed) + len(empty_dir_failed)} 个",
                ]
            )
        elif blocked_by_confirmation:
            lines.extend(
                [
                    "",
                    "当前为清理模式，但确认清理未开启。",
                    "请确认扫描结果无误后，再打开“确认清理”。",
                ]
            )
        else:
            lines.extend(
                [
                    "",
                    "当前模式：仅扫描。",
                    "如需删除，请切换为“清理”并开启“确认清理”。",
                ]
            )
        lines.extend(_target_summary_lines(targets, detail_limit))

        summary = {
            "total_bytes": sum(int(target["bytes"]) for target in targets),
            "total_text": _format_bytes(sum(int(target["bytes"]) for target in targets)),
            "cleanable_bytes": cleanable_bytes,
            "cleanable_text": _format_bytes(cleanable_bytes),
            "deleted_bytes": deleted_bytes,
            "deleted_text": _format_bytes(deleted_bytes),
            "file_count": sum(int(target["file_count"]) for target in targets),
            "cleanable_count": cleanable_count,
            "deleted_count": len(deleted),
            "removed_empty_dirs": removed_empty_dirs,
            "failed_count": len(failed) + len(empty_dir_failed),
        }
        payload = {
            "type": "lx_cache_cleanup_status",
            "version": 1,
            "mode": mode,
            "scope": scope,
            "confirmed": confirmed,
            "deleted": did_delete,
            "rules": {
                "keep_days": keep_days,
                "clean_orphans": True,
            },
            "summary": summary,
            "targets": targets,
            "deleted_files": deleted[:500],
            "failed": failed + empty_dir_failed,
        }
        status_json = json.dumps(payload, ensure_ascii=False, indent=2)
        return ("\n".join(lines), status_json)
