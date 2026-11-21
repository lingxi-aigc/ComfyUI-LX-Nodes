"""
LX_加载图像（文件夹）
每次运行只加载 1 张图片，支持格式过滤、排序、起始索引。

使用方式：
  自动递增：设置「运行次数」触发多次执行，节点从「索引」位置开始每次递增取图。
            索引=0 表示从第1张开始，索引=5 表示从第6张开始，递增到末尾后从头循环。
  固定索引：接 ComfyUI 自带 for 循环时，循环变量 i（从0开始）作为「索引」传入。
            节点直接按 i 值取图，不做内部递增。
  seed 参数：用于打破 ComfyUI 缓存机制；接 for 循环时由循环索引驱动（0,1,2…），
            支持 control_after_generate：点击后自动变为 fixed/increment/decrement/randomize。
"""

import os
import math
import hashlib
import threading
import time
import numpy as np
import torch
import folder_paths
from PIL import Image, ImageDraw, ImageFont
from typing import Tuple, List, Dict, Any, Optional

from .lxib_folder_scan import (
    PRESET_EXTS,
    SORT_DEFAULT,
    SORT_MODES,
    _RECURSION_DEPTH,
    build_cycle_queue,
    build_scan_stats,
    format_stats_text,
    output_folder_path,
    resolve_jump_position,
    scan_cache_key,
    root_mtime,
)
from .lxib_folder_shared import push_pending_empty_folders
from ..categories import LX_FOLDER_CATEGORY

MODE_AUTO = "自动递增"
MODE_FIXED = "固定索引"
INDEX_MODES = [MODE_AUTO, MODE_FIXED]


class LXLoadFolderImage:
    NODE_NAME = "LXImageBatch"
    CATEGORY = LX_FOLDER_CATEGORY
    SEARCH_ALIASES = [
        "lx",
        "LX",
        "灵犀",
        "加载图像（文件夹）",
        "LX_加载图像（文件夹）",
        "LXImageBatch",
        "文件夹加载",
        "批量加载",
        "lx folder image load",
    ]
    RETURN_TYPES = ("IMAGE", "STRING", "STRING", "STRING", "INT", "IMAGE", "STRING")
    RETURN_NAMES = ("图像", "文件夹名称", "图片名称", "数据统计", "图像总数", "实时进度预览", "文件夹路径")
    FUNCTION = "load_images"

    # 扫描缓存：key = scan_cache_key(root, ext, sort)
    _cache: Dict[str, Dict[str, Any]] = {}
    _cache_lock = threading.RLock()
    _cache_limit = 50

    # 各 key 的递增计数器（ordinal = 1-based），仅 MODE_AUTO 使用
    _counters: Dict[str, int] = {}

    # 各 key 的固定模式显示计数，仅 MODE_FIXED 使用
    _fixed_counters: Dict[str, int] = {}

    _font_cache: Dict[Tuple[int, bool], Any] = {}
    _progress_base_cache: Optional[Image.Image] = None

    @classmethod
    def INPUT_TYPES(cls):
        preset_keys = list(PRESET_EXTS.keys())
        return {
            "required": {
                "路径": (
                    "STRING",
                    {
                        "default": "",
                        "multiline": False,
                        "placeholder": "输入文件夹路径",
                    },
                ),
                "格式过滤": (preset_keys, {"default": "全部"}),
                "排序方式": (SORT_MODES, {"default": SORT_DEFAULT}),
                "模式": (INDEX_MODES, {"default": MODE_AUTO}),
                "索引": (
                    "INT",
                    {
                        "default": 0,
                        "min": 0,
                        "max": 999999,
                        "step": 1,
                        "tooltip": (
                            "自动递增：>0 仅首次生效作为起始位置（1、2、3…），=0 从第1张开始；"
                            "固定索引：直接用此值取图"
                        ),
                    },
                ),
                "seed": (
                    "INT",
                    {
                        "default": 0,
                        "min": 0,
                        "max": 0xFFFFFFFFFFFFFFFF,
                        "step": 1,
                        "control_after_generate": True,
                        "tooltip": (
                            "用于打破 ComfyUI 缓存机制；"
                            "接 for 循环时由循环索引驱动（0,1,2…），"
                            "否则使用默认值 0"
                        ),
                    },
                ),
                "显示预览": (
                    "BOOLEAN",
                    {
                        "default": True,
                        "label_on": "显示",
                        "label_off": "关闭",
                        "tooltip": "控制节点下方是否显示当前加载图片预览；关闭后仍会正常输出图像和进度信息。",
                    },
                ),
            },
            "optional": {},
        }

    # ------------------------------------------------------------------
    # 内部方法
    # ------------------------------------------------------------------

    def _get_scan(
        self,
        root: str,
        ext_preset: str,
        sort_mode: str,
    ) -> Dict[str, Any]:
        key = scan_cache_key(root, ext_preset, sort_mode)
        mtime = root_mtime(root)
        with self._cache_lock:
            cached = self._cache.get(key)
            if cached and cached.get("mtime") == mtime:
                return cached

            if len(self._cache) >= self._cache_limit:
                items = list(self._cache.items())
                self._cache = dict(items[len(items) // 2:])

            queue = build_cycle_queue(root, _RECURSION_DEPTH, ext_preset, sort_mode)
            # image_indices 与 queue 一起构建，避免 _pick 每次重新过滤
            image_indices = [i for i, x in enumerate(queue) if x["kind"] == "image"]
            entry = {
                "mtime": mtime,
                "queue": queue,
                "image_indices": image_indices,
                "stats": build_scan_stats(root, _RECURSION_DEPTH, queue, ext_preset),
            }
            self._cache[key] = entry
            return entry

    def _image_indices(self, queue: List[Dict[str, str]]) -> List[int]:
        return [i for i, x in enumerate(queue) if x["kind"] == "image"]

    def _pick(
        self,
        queue: List[Dict[str, str]],
        image_indices: List[int],
        root: str,
        ordinal: int,
        image_total: int,
    ) -> Optional[Dict[str, str]]:
        """
        按 1-based ordinal 从图片序列中取图。
        ordinal 超出 [1, image_total] 时由 resolve_jump_position 自动循环。
        """
        if not image_indices:
            return None
        target = resolve_jump_position(float(ordinal), image_total)
        idx = image_indices[target - 1]
        item = queue[idx]
        if item["kind"] == "empty":
            push_pending_empty_folders([output_folder_path(root, item["folder"])])
            return None
        return item

    # ------------------------------------------------------------------
    # 入口
    # ------------------------------------------------------------------

    def load_images(
        self,
        路径: str,
        格式过滤: str = "全部",
        排序方式: str = SORT_DEFAULT,
        模式: str = MODE_AUTO,
        索引: int = 0,
        seed: int = 0,
        显示预览: bool = True,
    ) -> Dict[str, Any]:
        if not 路径 or not os.path.isdir(路径):
            return self._pack_result(
                (None, "", "", "", 0, None, 路径),
                0, 0, "", "", 路径, "",
                show_preview=显示预览,
            )

        root = os.path.abspath(os.path.normpath(路径))
        scan = self._get_scan(root, 格式过滤, 排序方式)
        queue = list(scan["queue"])
        image_indices = list(scan["image_indices"])
        stats = scan["stats"]
        image_total = int(stats.get("total") or 0)

        pending_empty = [
            output_folder_path(root, item.get("folder", ""))
            for item in queue
            if item.get("kind") == "empty"
        ]
        pending_empty = [folder for folder in pending_empty if folder]
        if pending_empty:
            push_pending_empty_folders(pending_empty)

        if not queue or image_total == 0:
            stats_text = format_stats_text(stats, 0, "", "")
            return self._pack_result(
                (None, "", "", stats_text, image_total, None, 路径),
                0, image_total, "", "", 路径, stats_text,
                show_preview=显示预览,
            )

        key = scan_cache_key(root, 格式过滤, 排序方式)

        if 模式 == MODE_FIXED:
            # 固定索引：用「索引」取图，seed 仅用于打破缓存
            ordinal = 索引 + 1
            with self._cache_lock:
                if key in self._counters:
                    del self._counters[key]
                    self._fixed_counters[key] = 0
                display_idx = self._fixed_counters.get(key, 0)
                self._fixed_counters[key] = (display_idx + 1) % image_total
            item = self._pick(queue, image_indices, root, ordinal, image_total)
        else:
            # 自动递增：首次用「索引」作为起始 ordinal；点击重置按钮清空计数器后，
            # key 不在 counters 中，等价于首次，下次从索引+1 重新开始；之后每次 +1
            with self._cache_lock:
                if key not in self._counters:
                    ordinal = max(1, 索引 + 1)
                else:
                    ordinal = self._counters[key] + 1
                self._counters[key] = ordinal

            item = self._pick(queue, image_indices, root, ordinal, image_total)

        if item is None:
            stats_text = format_stats_text(stats, 0, "", "")
            return self._pack_result(
                (None, "", "", stats_text, image_total, None, 路径),
                0, image_total, "", "", 路径, stats_text,
                show_preview=显示预览,
            )

        folder_out = output_folder_path(root, item["folder"])
        ordinal = self._image_ordinal(stats, item["path"])
        next_name = self._next_relative_path(stats, ordinal)
        stats_text = format_stats_text(stats, ordinal, folder_out, item["name"], next_name=next_name)

        img_array = self._load_image(item["path"])
        if img_array is None:
            stats_text = format_stats_text(stats, ordinal, folder_out, item["name"], next_name=next_name)
            return self._pack_result(
                (None, folder_out, item["name"], stats_text, image_total, None, 路径),
                ordinal, image_total, folder_out, item["name"], 路径, stats_text,
                show_preview=显示预览,
            )

        images_tensor = torch.from_numpy(img_array[None, ...])
        ts = time.strftime("%H:%M:%S")
        display_path = f"{folder_out}/{item['name']}" if folder_out else item["name"]
        print(f"[LX_加载图像（文件夹）] [{ts}] 第 {ordinal}/{image_total} | {display_path}")

        return self._pack_result(
            (
                images_tensor,
                folder_out,
                item["name"],
                stats_text,
                image_total,
                None,
                路径,
            ),
            ordinal,
            image_total,
            folder_out,
            item["name"],
            路径,
            stats_text,
            next_name,
            item["path"],
            显示预览,
        )

    @staticmethod
    def _image_ordinal(stats: Dict[str, object], image_path: str) -> int:
        paths: List[str] = stats.get("image_paths_sorted") or []  # type: ignore
        try:
            return paths.index(image_path) + 1
        except ValueError:
            return 0

    @staticmethod
    def _next_relative_path(stats: Dict[str, object], ordinal: int) -> str:
        paths: List[str] = stats.get("image_paths_sorted") or []  # type: ignore
        root_path = str(stats.get("root_path") or "")
        if not paths or ordinal <= 0:
            return ""
        next_index = ordinal % len(paths)
        next_path = paths[next_index]
        if not root_path:
            return os.path.basename(next_path)
        try:
            return os.path.relpath(next_path, root_path).replace("\\", "/")
        except ValueError:
            return os.path.basename(next_path)

    @staticmethod
    def _load_image(image_path: str) -> Optional[np.ndarray]:
        try:
            with Image.open(image_path) as img:
                img = img.convert("RGB")
                return np.array(img).astype(np.float32) / 255.0
        except Exception:
            return None

    @staticmethod
    def _preview_image_result(image_path: str, image_name: str) -> Optional[Dict[str, str]]:
        if not image_path or not os.path.isfile(image_path):
            return None
        try:
            os.makedirs(folder_paths.get_temp_directory(), exist_ok=True)
            stem = os.path.splitext(os.path.basename(image_name or image_path))[0] or "image"
            safe_stem = "".join(ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in stem).strip("_") or "image"
            safe_stem = safe_stem[:80]
            source_mtime = os.path.getmtime(image_path)
            source_size = os.path.getsize(image_path)
            fingerprint = f"{os.path.abspath(image_path)}|{source_mtime}|{source_size}"
            digest = hashlib.md5(fingerprint.encode("utf-8")).hexdigest()[:10]
            preview_name = f"lx_load_preview_{safe_stem}_{digest}.png"
            preview_path = os.path.join(folder_paths.get_temp_directory(), preview_name)

            if not os.path.isfile(preview_path) or os.path.getmtime(preview_path) < source_mtime:
                with Image.open(image_path) as img:
                    img = img.convert("RGB")
                    img.save(preview_path, format="PNG", compress_level=1)

            return {
                "filename": preview_name,
                "subfolder": "",
                "type": "temp",
            }
        except Exception as exc:
            print(f"[LX_加载图像（文件夹）] 创建预览失败: {exc}")
            return None

    @staticmethod
    def _pack_result(
        result: Tuple[Any, str, str, str, int, Any, str],
        ordinal: int,
        image_total: int,
        current_folder: str,
        current_name: str,
        folder_path: str,
        stats_text: str,
        next_name: str = "",
        preview_path: str = "",
        show_preview: bool = True,
    ) -> Dict[str, Any]:
        current = f"{current_folder}/{current_name}" if current_folder else current_name
        payload = {
            "ordinal": int(ordinal or 0),
            "total": int(image_total or 0),
            "percent": int(round(100 * ordinal / image_total)) if image_total and ordinal else 0,
            "folder": current_folder or "",
            "name": current_name or "",
            "current": current or "暂无图片",
            "next": next_name or "",
            "path": folder_path or "",
            "stats": stats_text or "",
        }
        progress_image = LXLoadFolderImage._progress_image(payload)
        packed_result = result[:5] + (progress_image,) + result[6:]
        ui: Dict[str, Any] = {"lx_progress": [payload], "images": []}
        if show_preview:
            preview = LXLoadFolderImage._preview_image_result(preview_path, current_name)
            ui["images"] = [preview] if preview else []
        return {"ui": ui, "result": packed_result}

    @staticmethod
    def _load_font(size: int, bold: bool = False):
        cache_key = (int(size), bool(bold))
        cached = LXLoadFolderImage._font_cache.get(cache_key)
        if cached is not None:
            return cached
        candidates = [
            r"C:\Windows\Fonts\msyhbd.ttc" if bold else r"C:\Windows\Fonts\msyh.ttc",
            r"C:\Windows\Fonts\simhei.ttf",
            r"C:\Windows\Fonts\arialbd.ttf" if bold else r"C:\Windows\Fonts\arial.ttf",
        ]
        for path in candidates:
            try:
                if path and os.path.exists(path):
                    font = ImageFont.truetype(path, size=size)
                    LXLoadFolderImage._font_cache[cache_key] = font
                    return font
            except Exception:
                pass
        font = ImageFont.load_default()
        LXLoadFolderImage._font_cache[cache_key] = font
        return font

    @staticmethod
    def _fit_text(draw: ImageDraw.ImageDraw, text: Any, font, max_width: int) -> str:
        value = str(text or "")
        if draw.textlength(value, font=font) <= max_width:
            return value
        out = value
        while len(out) > 1 and draw.textlength(out + "...", font=font) > max_width:
            out = out[:-1]
        return out + "..."

    @staticmethod
    def _fit_middle_text(draw: ImageDraw.ImageDraw, text: Any, font, max_width: int) -> str:
        value = str(text or "")
        if draw.textlength(value, font=font) <= max_width:
            return value
        if max_width <= 0:
            return "..."

        left_len = max(4, len(value) // 2)
        right_len = max(4, len(value) - left_len)
        while left_len + right_len > 8:
            candidate = f"{value[:left_len]}...{value[-right_len:]}"
            if draw.textlength(candidate, font=font) <= max_width:
                return candidate
            if left_len > right_len:
                left_len -= 1
            else:
                right_len -= 1
        return LXLoadFolderImage._fit_text(draw, value, font, max_width)

    @staticmethod
    def _path_tail(path: Any) -> str:
        text = str(path or "").replace("\\", "/")
        if not text:
            return "未选择路径"
        parts = [p for p in text.split("/") if p]
        if len(parts) <= 2:
            return text
        return ".../" + "/".join(parts[-2:])

    @staticmethod
    def _progress_base_image() -> Image.Image:
        if LXLoadFolderImage._progress_base_cache is not None:
            return LXLoadFolderImage._progress_base_cache.copy()

        card_w, card_h = 1200, 800
        img = Image.new("RGB", (card_w, card_h), "#071523")
        draw = ImageDraw.Draw(img)

        draw.rectangle((0, 0, card_w, card_h), fill="#071523")
        draw.line((56, 122, card_w - 56, 122), fill="#173044", width=1)
        draw.line((472, 172, 472, 430), fill="#1c3547", width=1)

        title_font = LXLoadFolderImage._load_font(40, True)
        LXLoadFolderImage._draw_icon(draw, 56, 46, "folder", "#47d7ac", 52)
        draw.text((134, 46), "文件夹批量进度", font=title_font, fill="#f4fbf7")

        LXLoadFolderImage._progress_base_cache = img
        return img.copy()

    @staticmethod
    def _draw_icon(draw: ImageDraw.ImageDraw, x: int, y: int, kind: str, color: str, size: int = 28) -> None:
        size = max(int(size), 28)
        if kind == "image":
            draw.rounded_rectangle((x, y + 4, x + size, y + size - 2), radius=4, outline=color, width=3)
            draw.ellipse((x + size - 9, y + 9, x + size - 4, y + 14), fill=color)
            draw.polygon(
                [
                    (x + 5, y + size - 6),
                    (x + 12, y + size - 14),
                    (x + 18, y + size - 9),
                    (x + 23, y + size - 16),
                    (x + size - 4, y + size - 6),
                ],
                fill=color,
            )
        elif kind == "folder":
            body = "#47d7ac" if color.lower() != "#8295a2" else "#8295a2"
            front = "#55ddb6" if color.lower() != "#8295a2" else "#9aa8b1"
            stroke = "#1b8f7d" if color.lower() != "#8295a2" else "#60717b"
            draw.rounded_rectangle((x + 4, y + 8, x + size - 5, y + size - 3), radius=5, fill=body)
            draw.rounded_rectangle((x + 7, y + 4, x + size // 2 + 8, y + 15), radius=4, fill=body)
            draw.rounded_rectangle((x + 1, y + 16, x + size - 1, y + size), radius=6, fill=front, outline=stroke, width=max(1, size // 16))
        elif kind == "file":
            draw.rounded_rectangle((x + 4, y + 2, x + size - 3, y + size), radius=3, outline=color, width=3)
            draw.polygon([(x + size - 11, y + 3), (x + size - 3, y + 11), (x + size - 11, y + 11)], fill=color)
            draw.line((x + 9, y + 18, x + size - 9, y + 18), fill=color, width=2)
            draw.line((x + 9, y + 24, x + size - 13, y + 24), fill=color, width=2)
        elif kind == "stack":
            cx = x + size / 2
            top = y + size * 0.10
            layer_h = size * 0.24
            half_w = size * 0.38
            for offset in (size * 0.00, size * 0.27, size * 0.54):
                cy = top + offset
                draw.polygon(
                    [
                        (cx, cy),
                        (cx + half_w, cy + layer_h / 2),
                        (cx, cy + layer_h),
                        (cx - half_w, cy + layer_h / 2),
                    ],
                    fill=color,
                )

    @staticmethod
    def _draw_progress_ring(
        img: Image.Image,
        center: Tuple[int, int],
        radius: int,
        percent: int,
    ) -> None:
        scale = 2
        size = (radius + 34) * 2 * scale
        ring = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        d = ImageDraw.Draw(ring)
        cx = cy = size // 2
        rr = radius * scale
        box = (cx - rr, cy - rr, cx + rr, cy + rr)
        width = 18 * scale

        d.arc(box, 0, 360, fill=(18, 56, 70, 220), width=width)
        safe_percent = max(0, min(100, percent))
        start = -90
        end = start + int(360 * safe_percent / 100)
        if safe_percent > 0:
            d.arc(box, start, end, fill=(74, 229, 184, 255), width=width)

        ring = ring.resize((size // scale, size // scale), Image.Resampling.LANCZOS)
        x = center[0] - ring.size[0] // 2
        y = center[1] - ring.size[1] // 2
        img.paste(ring, (x, y), ring)

    @staticmethod
    def _progress_image(payload: Dict[str, Any]) -> torch.Tensor:
        card_w, card_h = 1200, 800
        total = int(payload.get("total") or 0)
        ordinal = int(payload.get("ordinal") or 0)
        percent = max(0, min(100, int(payload.get("percent") or 0)))
        remain = max(total - ordinal, 0)
        has_data = bool(total or ordinal or payload.get("name") or payload.get("path"))

        img = LXLoadFolderImage._progress_base_image()
        draw = ImageDraw.Draw(img)

        label_font = LXLoadFolderImage._load_font(20)
        value_font = LXLoadFolderImage._load_font(25, True)
        number_font = LXLoadFolderImage._load_font(48, True)
        percent_font = LXLoadFolderImage._load_font(88, True)
        current_font = LXLoadFolderImage._load_font(25, True)

        ring_center = (250, 292)
        LXLoadFolderImage._draw_progress_ring(img, ring_center, 150, percent)

        pct_text = f"{percent}%"
        pct_w = draw.textlength(pct_text, font=percent_font)
        draw.text((ring_center[0] - pct_w / 2, ring_center[1] - 68), pct_text, font=percent_font, fill="#48e1b5")
        done = "完成"
        done_font = LXLoadFolderImage._load_font(27, True)
        done_w = draw.textlength(done, font=done_font)
        draw.text((ring_center[0] - done_w / 2, ring_center[1] + 54), done, font=done_font, fill="#48e1b5")

        current_line = f"当前第 {ordinal if has_data else 0} 张 / 共 {total} 张"
        draw.text((540, 178), current_line, font=LXLoadFolderImage._load_font(30, True), fill="#f4fbf7")

        panel_x = 530
        card_w2 = 300
        stat_h = 154
        stats = [
            ("剩余图片", f"{remain}", "张", "image", "#48e1b5"),
            ("图像总数", f"{total}", "张", "stack", "#6ab7ff"),
        ]
        for i, (label, value, unit, icon, color) in enumerate(stats):
            x = panel_x + i * 318
            y = 250
            draw.rounded_rectangle((x, y, x + card_w2, y + stat_h), radius=24, fill="#0a1a2a", outline="#1f3b51", width=1)
            icon_box = (x + 38, y + 42, x + 108, y + 112)
            draw.ellipse(icon_box, fill="#102f39", outline="#1e6b6d", width=1)
            LXLoadFolderImage._draw_icon(draw, x + 52, y + 56, icon, color, 42)
            draw.text((x + 138, y + 42), label, font=label_font, fill="#b9c9d1")
            draw.text((x + 138, y + 84), value, font=number_font, fill=color)
            value_w = draw.textlength(value, font=number_font)
            draw.text((x + 152 + value_w, y + 110), unit, font=value_font, fill="#b9c9d1")

        bar_x, bar_y = 56, 492
        bar_w, bar_h = card_w - 112, 24
        draw.text((bar_x, bar_y - 44), "整体进度", font=value_font, fill="#dbe6df")
        draw.rounded_rectangle((bar_x, bar_y, bar_x + bar_w, bar_y + bar_h), radius=13, fill="#102032", outline="#1d4056", width=1)
        if percent > 0:
            fill_w = max(bar_h, int(bar_w * percent / 100))
            draw.rounded_rectangle((bar_x, bar_y, bar_x + fill_w, bar_y + bar_h), radius=13, fill="#48e1b5")

        current_name = LXLoadFolderImage._fit_middle_text(draw, payload.get("current") or "-", current_font, 430)
        next_name = LXLoadFolderImage._fit_middle_text(draw, payload.get("next") or "-", current_font, 430)
        path_name = LXLoadFolderImage._fit_text(draw, LXLoadFolderImage._path_tail(payload.get("path")), value_font, 700)

        info_y = 584
        info_h = 122
        draw.rounded_rectangle((56, info_y, card_w - 56, info_y + info_h), radius=22, fill="#0a1a2a", outline="#1f3b51", width=1)
        draw.line((card_w // 2, info_y + 28, card_w // 2, info_y + 94), fill="#1f3b51", width=1)
        LXLoadFolderImage._draw_icon(draw, 92, info_y + 44, "image", "#48e1b5", 32)
        draw.text((152, info_y + 28), "当前图片", font=label_font, fill="#9eb2bd")
        draw.text((152, info_y + 70), current_name, font=current_font, fill="#f4fbf7")
        LXLoadFolderImage._draw_icon(draw, card_w // 2 + 50, info_y + 44, "image", "#6ab7ff", 32)
        draw.text((card_w // 2 + 110, info_y + 28), "下一张", font=label_font, fill="#9eb2bd")
        draw.text((card_w // 2 + 110, info_y + 70), next_name, font=current_font, fill="#f4fbf7")

        LXLoadFolderImage._draw_icon(draw, 56, 744, "folder", "#8295a2", 24)
        draw.text((94, 742), "路径", font=value_font, fill="#8295a2")
        draw.text((172, 742), path_name, font=value_font, fill="#9eb2bd")

        array = np.asarray(img).astype(np.float32) / 255.0
        return torch.from_numpy(array[None, ...])


NODE_CLASS_MAPPINGS = {"LXImageBatch": LXLoadFolderImage}
NODE_DISPLAY_NAME_MAPPINGS = {"LXImageBatch": "加载图像（文件夹）"}
