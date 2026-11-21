"""
文件夹扫描工具

提供 imagebatch 插件所需的目录遍历、图像过滤、排序、统计等功能。
"""

import os
import re
import hashlib
from typing import Dict, List, Tuple, Any, Optional

# ─── 图像格式预设 ───────────────────────────────────────────────────────────

PRESET_EXTS: Dict[str, Tuple[str, ...]] = {
    "全部": (".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif", ".tiff", ".tif", ".ico"),
    "PNG": (".png",),
    "JPG": (".jpg", ".jpeg"),
    "WEBP": (".webp",),
}

FORMAT_LABELS: Dict[str, str] = {
    "全部": "全部图片格式",
    "PNG": "png",
    "JPG": "jpg",
    "WEBP": "webp",
}

SORT_DEFAULT = "默认"
SORT_MODES = ["默认", "时间↓", "时间↑", "A→Z", "Z→A", "大小↓", "大小↑"]
_RECURSION_DEPTH: Optional[int] = None


def output_folder_path(root: str, folder: str) -> str:
    """保存用相对路径：仅输出子目录；主目录直下图片返回空字符串。"""
    if not folder or folder == ".":
        return ""
    return str(folder).strip().replace("\\", "/").strip("/")


def root_mtime(root: str) -> float:
    """返回目录树最新修改时间，递归子目录，避免深层文件变化后缓存不刷新。"""
    latest = 0.0
    try:
        root = os.path.abspath(root)
        latest = max(latest, os.path.getmtime(root))
        for current, dirs, files in os.walk(root):
            dirs[:] = [d for d in dirs if not d.startswith(".")]
            try:
                latest = max(latest, os.path.getmtime(current))
            except OSError:
                pass
            for name in files:
                if name.startswith("."):
                    continue
                try:
                    latest = max(latest, os.path.getmtime(os.path.join(current, name)))
                except OSError:
                    pass
    except OSError:
        return 0.0
    return latest


def scan_cache_key(root: str, ext_preset: str, sort_mode: str) -> str:
    """生成扫描缓存 key（root + 过滤预设 + 排序方式）。"""
    return hashlib.md5(f"{root}|{ext_preset}|{sort_mode}".encode()).hexdigest()


def resolve_jump_position(ordinal: float, image_total: int) -> int:
    """将任意实数 ordinal 解析为 1-based 整数索引，超出范围时循环。

    ordinal: 浮点数值（1-based）
    image_total: 图像总数
    返回: 1-based 整数索引
    """
    if image_total <= 0:
        return 1
    idx = int(ordinal) - 1  # 转 0-based
    idx = idx % image_total
    return idx + 1  # 回 1-based


def _sort_key(path: str, mode: str, root: str = "") -> Any:
    """返回排序 key 元组；非默认排序按整棵目录的相对路径兜底，避免同名图片顺序不稳定。"""
    try:
        mtime = os.path.getmtime(path)
        size = os.path.getsize(path)
    except OSError:
        mtime = 0.0
        size = 0
    if root:
        try:
            name = os.path.relpath(path, root).replace("\\", "/")
        except ValueError:
            name = os.path.basename(path)
    else:
        name = os.path.basename(path)
    name_key = name.lower()
    if mode == "时间↓":
        return (-mtime, name_key)
    elif mode == "时间↑":
        return (mtime, name_key)
    elif mode == "A→Z":
        return (name_key,)
    elif mode == "Z→A":
        return (name_key,)
    elif mode == "大小↓":
        return (-size, name_key)
    elif mode == "大小↑":
        return (size, name_key)
    else:
        return (0, name_key)


def build_cycle_queue(
    root: str,
    max_depth: Optional[int],
    ext_preset: str,
    sort_mode: str = "默认",
) -> List[Dict[str, str]]:
    """递归遍历 root 目录，返回按 sort_mode 排序后的图像队列。

    返回格式：
        {"kind": "image",  "folder": "...", "name": "...", "path": "..."}
        {"kind": "empty",   "folder": "...", "name": "...", "path": ""}
    """
    exts = PRESET_EXTS.get(ext_preset, PRESET_EXTS["全部"])
    ext_pattern = re.compile(
        "^(" + "|".join(re.escape(e) for e in exts) + ")$",
        re.IGNORECASE,
    )

    result: List[Dict[str, str]] = []
    images: List[Dict[str, str]] = []
    empty_folders: List[Dict[str, str]] = []
    root = os.path.abspath(root)

    def walk(rel_folder: str, depth: int) -> None:
        if max_depth is not None and depth > max_depth:
            return
        abs_folder = os.path.join(root, rel_folder) if rel_folder else root
        try:
            entries = os.listdir(abs_folder)
        except OSError:
            return

        items: List[Tuple[Any, str]] = []
        sub_folders: List[str] = []

        for entry in entries:
            if entry.startswith("."):
                continue
            abs_path = os.path.join(abs_folder, entry)
            if os.path.isdir(abs_path):
                sub_folders.append(entry)
            elif os.path.isfile(abs_path):
                if ext_pattern.search(os.path.splitext(entry)[1]):
                    items.append((abs_path, entry))

        # 排序
        if sort_mode != "默认" and items:
            items.sort(key=lambda x: _sort_key(x[0], sort_mode))

        folder_label = rel_folder if rel_folder else "."
        for abs_path, entry in items:
            image_item = {
                "kind": "image",
                "folder": folder_label,
                "name": entry,
                "path": abs_path,
            }
            images.append(image_item)
            if sort_mode == "默认":
                result.append(image_item)

        if not items and not sub_folders:
            empty_item = {
                "kind": "empty",
                "folder": folder_label,
                "name": "",
                "path": "",
            }
            empty_folders.append(empty_item)
            if sort_mode == "默认":
                result.append(empty_item)

        for sub in sorted(sub_folders):
            walk(os.path.join(rel_folder, sub) if rel_folder else sub, depth + 1)

    walk("", 0)
    if sort_mode != "默认":
        images.sort(
            key=lambda item: _sort_key(item["path"], sort_mode, root),
            reverse=(sort_mode == "Z→A"),
        )
        result = images + empty_folders
    return result


def build_scan_stats(
    root: str,
    max_depth: Optional[int],
    queue: List[Dict[str, str]],
    ext_preset: str = "全部",
) -> Dict[str, Any]:
    """统计主目录、所有子文件夹、主目录直下图片、空文件夹和排序后的图片路径。"""
    root = os.path.abspath(os.path.normpath(root))
    image_paths = [item["path"] for item in queue if item.get("kind") == "image"]
    empty_folders = [
        output_folder_path(root, item.get("folder", ""))
        for item in queue
        if item.get("kind") == "empty"
    ]
    empty_folders = [folder for folder in empty_folders if folder]

    all_subdirs: List[str] = []
    try:
        for current, dirs, _files in os.walk(root):
            dirs[:] = sorted(d for d in dirs if not d.startswith("."))
            for dirname in dirs:
                abs_path = os.path.join(current, dirname)
                rel = os.path.relpath(abs_path, root).replace("\\", "/")
                all_subdirs.append(rel)
    except OSError:
        pass

    folder_counts: Dict[str, int] = {name: 0 for name in all_subdirs}
    for path in image_paths:
        rel = os.path.relpath(path, root).replace("\\", "/")
        folder = os.path.dirname(rel).replace("\\", "/")
        if folder:
            folder_counts[folder] = folder_counts.get(folder, 0) + 1

    per_folder: List[Tuple[str, int]] = sorted(folder_counts.items(), key=lambda x: x[0].lower())

    root_direct_count = sum(
        1
        for path in image_paths
        if "/" not in os.path.relpath(path, root).replace("\\", "/")
    )

    return {
        "main_name": os.path.basename(os.path.normpath(root)),
        "root_path": root.replace("\\", "/"),
        "subfolder_count": len(all_subdirs),
        "per_folder": per_folder,
        "root_direct_count": root_direct_count,
        "empty_folders": sorted(set(empty_folders)),
        "total": len(image_paths),
        "image_paths_sorted": list(image_paths),
        "format_label": FORMAT_LABELS.get(ext_preset, str(ext_preset or "全部").lower()),
    }


def format_stats_text(
    stats: Dict[str, Any],
    ordinal: int,
    folder: str,
    name: str,
    next_name: str = "",
) -> str:
    """生成适合展示给用户的目录扫描与进度文本。"""
    def _progress_bar(current: int, total: int, width: int = 10) -> Tuple[str, float]:
        if total <= 0 or current <= 0:
            return "░" * width, 0.0
        percent_value = min(max(current / total, 0.0), 1.0)
        filled = int(round(percent_value * width))
        return "█" * filled + "░" * (width - filled), percent_value * 100

    def _tree_lines(main_name: str, root_count: int, per_folder: List[Tuple[str, int]], current_folder: str) -> List[str]:
        tree: Dict[str, Dict[str, Any]] = {}

        def node_for(path: str) -> Dict[str, Any]:
            current = tree
            node: Dict[str, Any] = {}
            for part in [p for p in path.split("/") if p]:
                node = current.setdefault(part, {"count": 0, "children": {}})
                current = node["children"]
            return node

        for folder_name, count in per_folder:
            node = node_for(folder_name)
            node["count"] = int(count or 0)

        lines_out = [f"{main_name}/" if main_name else "根目录/"]
        entries: List[Tuple[str, int, Dict[str, Any]]] = []
        if root_count > 0:
            entries.append(("根目录", root_count, {"count": root_count, "children": {}}))
        entries.extend((name, data.get("count", 0), data) for name, data in sorted(tree.items(), key=lambda x: x[0].lower()))

        def render(entries_in: List[Tuple[str, int, Dict[str, Any]]], prefix: str = "", parent_path: str = "") -> None:
            for index, (name_in, count_in, data_in) in enumerate(entries_in):
                is_last = index == len(entries_in) - 1
                branch = "└─ " if is_last else "├─ "
                full_path = f"{parent_path}/{name_in}" if parent_path else name_in
                marker = " ← 处理中" if current_folder == full_path else ""
                lines_out.append(f"{prefix}{branch}{name_in} {int(count_in or 0)} 张{marker}")
                children = data_in.get("children") or {}
                child_entries = [
                    (child_name, child_data.get("count", 0), child_data)
                    for child_name, child_data in sorted(children.items(), key=lambda x: x[0].lower())
                ]
                if child_entries:
                    child_prefix = prefix + ("   " if is_last else "│  ")
                    render(child_entries, child_prefix, full_path)

        if entries:
            render(entries)
        else:
            lines_out.append("└─ 根目录 0 张")
        return lines_out

    lines: List[str] = []
    main_name = str(stats.get("main_name") or "")
    root_path = str(stats.get("root_path") or "")
    per_folder: List[Tuple[str, int]] = list(stats.get("per_folder") or [])
    root_direct_count = int(stats.get("root_direct_count") or 0)
    total = int(stats.get("total") or 0)
    subfolder_image_count = max(total - root_direct_count, 0)
    subfolder_count = int(stats.get("subfolder_count") or 0)
    image_paths: List[str] = list(stats.get("image_paths_sorted") or [])
    current = f"{folder}/{name}" if folder else name
    if not next_name and total > 0 and ordinal > 0 and image_paths:
        next_index = ordinal % total
        next_path = image_paths[next_index] if 0 <= next_index < len(image_paths) else ""
        if root_path and next_path:
            next_name = os.path.relpath(next_path, root_path).replace("\\", "/")
    bar, percent = _progress_bar(ordinal, total)
    remaining = max(total - int(ordinal or 0), 0)

    lines.append(f"📁 {main_name or '图像文件夹'}")
    lines.append(f"路径：{root_path or '-'}")
    lines.append(f"格式：{stats.get('format_label') or '全部图片格式'}")
    lines.append("")
    lines.append("🔎 扫描汇总")
    lines.append(f"总计：{total} 张图片")
    lines.append(f"根目录：{root_direct_count} 张")
    lines.append(f"子文件夹：{subfolder_image_count} 张｜{subfolder_count} 个子文件夹")
    lines.append("")
    lines.append("━━━━━━━━━━━━━━━━━━━━")
    lines.append("")
    lines.append("📍 当前进度")
    lines.append(f"第 {int(ordinal or 0)} / {total} 张 {bar} {percent:.1f}%")
    lines.append("")
    lines.append(f"当前：{current or '-'}")
    lines.append(f"下一张：{next_name or '-'}")
    lines.append(f"剩余：{remaining} 张")
    lines.append("")
    lines.append("━━━━━━━━━━━━━━━━━━━━")
    lines.append("")
    lines.append("📂 目录结构")
    lines.append("")
    lines.extend(_tree_lines(main_name, root_direct_count, per_folder, folder or ""))

    return "\n".join(lines)
