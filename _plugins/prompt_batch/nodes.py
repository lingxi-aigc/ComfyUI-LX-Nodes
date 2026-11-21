"""Batch TXT prompt loading and series-aware image saving for ComfyUI."""

from __future__ import annotations

import hashlib
import json
import os
import re
import threading
import uuid
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Sequence, Tuple

import folder_paths
import numpy as np
import torch
from comfy_execution.graph import ExecutionBlocker
from PIL import Image, ImageDraw, ImageFont
from PIL.PngImagePlugin import PngInfo

from ..categories import LX_FOLDER_CATEGORY


CATEGORY = LX_FOLDER_CATEGORY

READ_SINGLE = "单个TXT"
READ_FOLDER = "TXT文件夹"
READ_MODES = [READ_SINGLE, READ_FOLDER]

SORT_ASC = "自然升序"
SORT_DESC = "自然降序"
SORT_MODES = [SORT_ASC, SORT_DESC]

MODE_AUTO = "自动递增"
MODE_FIXED = "固定索引"
INDEX_MODES = [MODE_AUTO, MODE_FIXED]

SAVE_FORMATS = ["PNG", "JPG", "WEBP"]
FORMAT_EXTENSIONS = {
    "PNG": ".png",
    "JPG": ".jpg",
    "WEBP": ".webp",
}

PROGRESS_EVENT = "lx-prompt-batch-progress"
PROGRESS_UI_KEY = "lx_prompt_progress_preview"
PROGRESS_OUTPUT_INDEX = 5
STATS_OUTPUT_INDEX = 3

_NATURAL_PARTS = re.compile(r"(\d+)")
_INVALID_FILENAME_CHARS = '<>:"/\\|?*'
_WINDOWS_RESERVED_NAMES = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}


def _unwrap_path(value: str) -> str:
    path = str(value or "").strip()
    if len(path) >= 2 and path[0] == path[-1] and path[0] in {"'", '"'}:
        path = path[1:-1].strip()
    return path


def _normalize_path(value: str) -> str:
    path = os.path.expandvars(os.path.expanduser(_unwrap_path(value)))
    return os.path.abspath(os.path.normpath(path))


def _natural_key(value: str) -> Tuple[Any, ...]:
    parts = _NATURAL_PARTS.split(str(value).casefold())
    return tuple(int(part) if part.isdigit() else part for part in parts)


def _decode_txt(path: str) -> str:
    with open(path, "rb") as handle:
        data = handle.read()

    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        return data.decode("utf-16")

    last_error: UnicodeDecodeError | None = None
    for encoding in ("utf-8-sig", "gb18030"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError as exc:
            last_error = exc

    if last_error is not None:
        raise ValueError(f"无法识别 TXT 编码：{path}") from last_error
    return ""


def _read_prompt_lines(path: str) -> List[str]:
    prompts: List[str] = []
    for line in _decode_txt(path).splitlines():
        prompt = line.strip()
        if prompt:
            prompts.append(prompt)
    return prompts


def _sanitize_component(value: str, fallback: str, limit: int = 120) -> str:
    text = str(value or "").strip()
    text = "".join(
        "_" if char in _INVALID_FILENAME_CHARS or ord(char) < 32 else char
        for char in text
    )
    text = text.strip().rstrip(". ")
    if text.upper() in _WINDOWS_RESERVED_NAMES:
        text = f"_{text}"
    text = text[:limit].rstrip(". ")
    return text or fallback


def _sanitize_affix(value: str) -> str:
    return _sanitize_component(value, "", limit=80) if str(value or "").strip() else ""


@dataclass(frozen=True)
class _PromptTask:
    prompt: str
    folder_name: str
    image_name: str
    txt_path: str
    series_index: int
    series_total: int
    prompt_index: int
    series_prompt_total: int
    global_index: int
    prompt_total: int


@dataclass(frozen=True)
class _PromptScan:
    source_path: str
    signature: Tuple[Any, ...]
    txt_total: int
    empty_txt_total: int
    prompt_total: int
    series_counts: Tuple[Tuple[str, int], ...]
    tasks: Tuple[_PromptTask, ...]


class LXPromptBatchLoader:
    """Load one non-empty TXT line per execution and expose series progress."""

    DESCRIPTION = (
        "单个 TXT 或 TXT 文件夹批量提示词加载器。一个 TXT 代表一个系列，"
        "每个非空行代表一条提示词。"
    )
    SEARCH_ALIASES = [
        "lx",
        "LX",
        "灵犀",
        "提示词批量",
        "加载提示词",
        "TXT提示词",
        "prompt batch",
        "prompt txt loader",
    ]
    CATEGORY = CATEGORY
    FUNCTION = "load_prompt"
    RETURN_TYPES = ("STRING", "STRING", "STRING", "STRING", "INT", "IMAGE", "STRING")
    RETURN_NAMES = (
        "提示词",
        "文件夹名称",
        "图片名称",
        "数据统计",
        "提示词总数",
        "实时进度预览",
        "文件夹路径",
    )

    _cache: Dict[Tuple[str, str, str], _PromptScan] = {}
    _counters: Dict[Tuple[str, int, Tuple[str, str, str]], int] = {}
    _lock = threading.RLock()
    _cache_limit = 32
    _font_cache: Dict[Tuple[int, bool], Any] = {}
    _progress_base_cache: Image.Image | None = None

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "读取类型": (READ_MODES, {"default": READ_FOLDER}),
                "路径": (
                    "STRING",
                    {
                        "default": "",
                        "multiline": False,
                        "placeholder": "输入 TXT 文件或文件夹路径",
                    },
                ),
                "文件排序": (SORT_MODES, {"default": SORT_ASC}),
                "模式": (INDEX_MODES, {"default": MODE_AUTO}),
                "索引": (
                    "INT",
                    {
                        "default": 0,
                        "min": 0,
                        "max": 999999999,
                        "step": 1,
                        "tooltip": "全局任务索引，从 0 开始。",
                    },
                ),
                "重置版本": (
                    "INT",
                    {
                        "default": 0,
                        "min": 0,
                        "max": 0x7FFFFFFF,
                        "step": 1,
                        "tooltip": "内部计数器版本，由“重置计数器”按钮自动更新。",
                    },
                ),
            },
            "hidden": {
                "unique_id": "UNIQUE_ID",
                "prompt": "PROMPT",
            },
        }

    @classmethod
    def IS_CHANGED(cls, **_kwargs):
        # 自动递增依赖每次执行都重新进入本节点，不能被 ComfyUI 缓存跳过。
        return float("nan")

    @classmethod
    def reset_counter(cls, node_id: str | None = None) -> int:
        removed = 0
        with cls._lock:
            if not node_id:
                removed = len(cls._counters)
                cls._counters.clear()
                return removed
            for key in list(cls._counters):
                if key[0] == str(node_id):
                    del cls._counters[key]
                    removed += 1
        cls._clear_progress_previews(node_id)
        return removed

    @staticmethod
    def _counter_key(
        node_id: str | int | None,
        reset_version: int,
        read_mode: str,
        source_path: str,
        sort_mode: str,
    ) -> Tuple[str, int, Tuple[str, str, str]]:
        return (
            str(node_id or "global"),
            int(reset_version),
            (str(read_mode), str(source_path), str(sort_mode)),
        )

    @classmethod
    def _counter_value(
        cls,
        counter_key: Tuple[str, int, Tuple[str, str, str]],
        fallback_index: int,
    ) -> int:
        with cls._lock:
            node_key, reset_version, cache_key = counter_key
            for old_key in list(cls._counters):
                if (
                    old_key[0] == node_key
                    and old_key[2] == cache_key
                    and old_key[1] != reset_version
                ):
                    del cls._counters[old_key]
            return cls._counters.get(counter_key, max(0, int(fallback_index)))

    @staticmethod
    def _source_files(source_path: str, read_mode: str, sort_mode: str) -> List[str]:
        if not source_path:
            raise ValueError("请填写 TXT 文件或文件夹路径。")

        if read_mode == READ_SINGLE:
            if not os.path.isfile(source_path):
                raise ValueError(f"TXT 文件不存在：{source_path}")
            if os.path.splitext(source_path)[1].casefold() != ".txt":
                raise ValueError("单个文件模式只支持 .txt 文件。")
            return [source_path]

        if not os.path.isdir(source_path):
            raise ValueError(f"TXT 文件夹不存在：{source_path}")

        files = [
            os.path.join(source_path, name)
            for name in os.listdir(source_path)
            if os.path.isfile(os.path.join(source_path, name))
            and os.path.splitext(name)[1].casefold() == ".txt"
        ]
        files.sort(
            key=lambda item: _natural_key(os.path.basename(item)),
            reverse=sort_mode == SORT_DESC,
        )
        return files

    @staticmethod
    def _signature(files: Iterable[str]) -> Tuple[Any, ...]:
        signature: List[Any] = []
        for path in files:
            stat = os.stat(path)
            signature.append(
                (
                    os.path.normcase(os.path.abspath(path)),
                    int(getattr(stat, "st_mtime_ns", int(stat.st_mtime * 1_000_000_000))),
                    int(stat.st_size),
                )
            )
        return tuple(signature)

    @classmethod
    def _build_scan(
        cls,
        source_path: str,
        read_mode: str,
        sort_mode: str,
    ) -> _PromptScan:
        files = cls._source_files(source_path, read_mode, sort_mode)
        signature = cls._signature(files)
        cache_key = (read_mode, source_path, sort_mode)

        with cls._lock:
            cached = cls._cache.get(cache_key)
            if cached is not None and cached.signature == signature:
                return cached

        prompt_groups: List[Tuple[str, List[str]]] = [
            (path, _read_prompt_lines(path))
            for path in files
        ]
        prompt_total = sum(len(prompts) for _, prompts in prompt_groups)
        tasks: List[_PromptTask] = []

        for series_index, (txt_path, prompts) in enumerate(prompt_groups, start=1):
            folder_name = os.path.splitext(os.path.basename(txt_path))[0].strip() or f"系列{series_index}"
            pad_width = max(3, len(str(max(1, len(prompts)))))
            for prompt_index, prompt in enumerate(prompts, start=1):
                tasks.append(
                    _PromptTask(
                        prompt=prompt,
                        folder_name=folder_name,
                        image_name=str(prompt_index).zfill(pad_width),
                        txt_path=txt_path,
                        series_index=series_index,
                        series_total=len(prompt_groups),
                        prompt_index=prompt_index,
                        series_prompt_total=len(prompts),
                        global_index=len(tasks) + 1,
                        prompt_total=prompt_total,
                    )
                )

        scan = _PromptScan(
            source_path=source_path,
            signature=signature,
            txt_total=len(files),
            empty_txt_total=sum(1 for _, prompts in prompt_groups if not prompts),
            prompt_total=prompt_total,
            series_counts=tuple(
                (os.path.basename(path), len(prompts))
                for path, prompts in prompt_groups
            ),
            tasks=tuple(tasks),
        )

        with cls._lock:
            if len(cls._cache) >= cls._cache_limit:
                oldest_keys = list(cls._cache)[: max(1, cls._cache_limit // 2)]
                for key in oldest_keys:
                    cls._cache.pop(key, None)
            cls._cache[cache_key] = scan
        return scan

    @staticmethod
    def _stats_text(
        scan: _PromptScan,
        task: _PromptTask,
        read_mode: str,
        sort_mode: str,
        completed_count: int | None = None,
        phase: str = "处理中",
    ) -> str:
        completed = (
            task.global_index
            if completed_count is None
            else max(0, min(scan.prompt_total, int(completed_count)))
        )
        percent = 100.0 * completed / max(1, scan.prompt_total)
        bar_length = 20
        filled = min(
            bar_length,
            max(0, int(round(bar_length * percent / 100.0))),
        )
        progress_bar = "█" * filled + "░" * (bar_length - filled)
        remaining = max(0, scan.prompt_total - completed)

        current_txt = os.path.basename(task.txt_path)
        if completed >= scan.prompt_total:
            next_text = "全部完成"
        elif task.global_index < scan.prompt_total:
            next_task = scan.tasks[task.global_index]
            next_text = (
                f"{os.path.basename(next_task.txt_path)} / "
                f"第 {next_task.prompt_index} 条"
            )
        else:
            next_text = "已是最后一条"

        source_path = scan.source_path.replace("\\", "/")
        if read_mode == READ_SINGLE:
            structure_root = os.path.basename(os.path.dirname(scan.source_path)) or "当前目录"
        else:
            structure_root = os.path.basename(scan.source_path.rstrip("\\/")) or scan.source_path

        lines = [
            "📁 TXT 提示词批量任务",
            f"路径：{source_path}",
            f"读取：{read_mode}｜排序：{sort_mode}",
            "",
            "🔎 扫描汇总",
            f"TXT：{scan.txt_total} 个",
            f"提示词：{scan.prompt_total} 条",
            f"空 TXT：{scan.empty_txt_total} 个",
            "",
            "────────────────────────",
            "📍 当前进度",
            (
                f"已完成 {completed} / {scan.prompt_total} 条 "
                f"{progress_bar} {percent:.1f}%"
            ),
            f"状态：{phase}",
            f"当前：{current_txt} / 第 {task.prompt_index} 条",
            f"下一条：{next_text}",
            f"系列进度：{task.prompt_index} / {task.series_prompt_total}",
            f"剩余：{remaining} 条",
            "",
            "────────────────────────",
            "📂 TXT 结构",
            f"{structure_root}/",
        ]

        last_index = len(scan.series_counts)
        for index, (txt_name, prompt_count) in enumerate(scan.series_counts, start=1):
            branch = "└─" if index == last_index else "├─"
            marker = "  ← 处理中" if index == task.series_index else ""
            lines.append(
                f"{branch} {txt_name}  {prompt_count} 条{marker}"
            )
        return "\n".join(lines)

    @classmethod
    def _load_font(cls, size: int, bold: bool = False):
        cache_key = (int(size), bool(bold))
        cached = cls._font_cache.get(cache_key)
        if cached is not None:
            return cached

        candidates = [
            r"C:\Windows\Fonts\msyhbd.ttc" if bold else r"C:\Windows\Fonts\msyh.ttc",
            r"C:\Windows\Fonts\simhei.ttf",
            r"C:\Windows\Fonts\arialbd.ttf" if bold else r"C:\Windows\Fonts\arial.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
            if bold
            else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        ]
        for font_path in candidates:
            try:
                if os.path.isfile(font_path):
                    font = ImageFont.truetype(font_path, size=size)
                    cls._font_cache[cache_key] = font
                    return font
            except Exception:
                continue

        font = ImageFont.load_default()
        cls._font_cache[cache_key] = font
        return font

    @staticmethod
    def _fit_text(
        draw: ImageDraw.ImageDraw,
        value: Any,
        font: Any,
        max_width: int,
    ) -> str:
        text = str(value or "")
        if draw.textlength(text, font=font) <= max_width:
            return text
        output = text
        while len(output) > 1 and draw.textlength(f"{output}…", font=font) > max_width:
            output = output[:-1]
        return f"{output}…"

    @staticmethod
    def _fit_middle_text(
        draw: ImageDraw.ImageDraw,
        value: Any,
        font: Any,
        max_width: int,
    ) -> str:
        text = str(value or "")
        if draw.textlength(text, font=font) <= max_width:
            return text
        if max_width <= 0:
            return "…"

        left_length = max(4, len(text) // 2)
        right_length = max(4, len(text) - left_length)
        while left_length + right_length > 8:
            candidate = f"{text[:left_length]}…{text[-right_length:]}"
            if draw.textlength(candidate, font=font) <= max_width:
                return candidate
            if left_length > right_length:
                left_length -= 1
            else:
                right_length -= 1
        return LXPromptBatchLoader._fit_text(draw, text, font, max_width)

    @staticmethod
    def _path_tail(value: Any) -> str:
        text = str(value or "").replace("\\", "/")
        if not text:
            return "未选择路径"
        parts = [part for part in text.split("/") if part]
        if len(parts) <= 2:
            return text
        return "…/" + "/".join(parts[-2:])

    @staticmethod
    def _draw_icon(
        draw: ImageDraw.ImageDraw,
        x: int,
        y: int,
        kind: str,
        color: str,
        size: int = 28,
    ) -> None:
        size = max(int(size), 28)
        if kind == "folder":
            muted = color.casefold() == "#8295a2"
            body = "#8295a2" if muted else "#47d7ac"
            front = "#9aa8b1" if muted else "#55ddb6"
            stroke = "#60717b" if muted else "#1b8f7d"
            draw.rounded_rectangle(
                (x + 4, y + 8, x + size - 5, y + size - 3),
                radius=5,
                fill=body,
            )
            draw.rounded_rectangle(
                (x + 7, y + 4, x + size // 2 + 8, y + 15),
                radius=4,
                fill=body,
            )
            draw.rounded_rectangle(
                (x + 1, y + 16, x + size - 1, y + size),
                radius=6,
                fill=front,
                outline=stroke,
                width=max(1, size // 16),
            )
        elif kind == "file":
            draw.rounded_rectangle(
                (x + 4, y + 2, x + size - 3, y + size),
                radius=3,
                outline=color,
                width=3,
            )
            draw.polygon(
                [
                    (x + size - 11, y + 3),
                    (x + size - 3, y + 11),
                    (x + size - 11, y + 11),
                ],
                fill=color,
            )
            draw.line((x + 9, y + 18, x + size - 9, y + 18), fill=color, width=2)
            draw.line((x + 9, y + 24, x + size - 13, y + 24), fill=color, width=2)
        elif kind == "stack":
            center_x = x + size / 2
            top = y + size * 0.10
            layer_height = size * 0.24
            half_width = size * 0.38
            for offset in (size * 0.00, size * 0.27, size * 0.54):
                center_y = top + offset
                draw.polygon(
                    [
                        (center_x, center_y),
                        (center_x + half_width, center_y + layer_height / 2),
                        (center_x, center_y + layer_height),
                        (center_x - half_width, center_y + layer_height / 2),
                    ],
                    fill=color,
                )

    @classmethod
    def _progress_base_image(cls) -> Image.Image:
        if cls._progress_base_cache is not None:
            return cls._progress_base_cache.copy()

        width, height = 1200, 800
        image = Image.new("RGB", (width, height), "#071523")
        draw = ImageDraw.Draw(image)
        draw.line((56, 122, width - 56, 122), fill="#173044", width=1)
        draw.line((472, 172, 472, 430), fill="#1c3547", width=1)

        cls._draw_icon(draw, 56, 46, "folder", "#47d7ac", 52)
        draw.text(
            (134, 46),
            "提示词批量进度",
            font=cls._load_font(40, True),
            fill="#f4fbf7",
        )

        cls._progress_base_cache = image
        return image.copy()

    @staticmethod
    def _draw_progress_ring(
        image: Image.Image,
        center: Tuple[int, int],
        radius: int,
        percent: int,
    ) -> None:
        scale = 2
        size = (radius + 34) * 2 * scale
        ring = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        draw = ImageDraw.Draw(ring)
        center_x = center_y = size // 2
        scaled_radius = radius * scale
        box = (
            center_x - scaled_radius,
            center_y - scaled_radius,
            center_x + scaled_radius,
            center_y + scaled_radius,
        )
        line_width = 18 * scale

        draw.arc(box, 0, 360, fill=(18, 56, 70, 220), width=line_width)
        safe_percent = max(0, min(100, int(percent)))
        if safe_percent > 0:
            draw.arc(
                box,
                -90,
                -90 + int(360 * safe_percent / 100),
                fill=(74, 229, 184, 255),
                width=line_width,
            )

        ring = ring.resize((size // scale, size // scale), Image.Resampling.LANCZOS)
        image.paste(
            ring,
            (
                center[0] - ring.size[0] // 2,
                center[1] - ring.size[1] // 2,
            ),
            ring,
        )

    @classmethod
    def _progress_image(
        cls,
        scan: _PromptScan,
        task: _PromptTask,
        completed_count: int | None = None,
        phase: str = "处理中",
    ) -> torch.Tensor:
        width = 1200
        total = max(0, int(task.prompt_total))
        completed = (
            task.global_index
            if completed_count is None
            else max(0, min(total, int(completed_count)))
        )
        percent = max(0, min(100, int(round(100 * completed / max(1, total)))))
        remaining = max(0, total - completed)

        image = cls._progress_base_image()
        draw = ImageDraw.Draw(image)

        label_font = cls._load_font(20)
        value_font = cls._load_font(25, True)
        number_font = cls._load_font(48, True)
        percent_font = cls._load_font(88, True)
        current_font = cls._load_font(25, True)

        ring_center = (250, 292)
        cls._draw_progress_ring(image, ring_center, 150, percent)
        percent_text = f"{percent}%"
        percent_width = draw.textlength(percent_text, font=percent_font)
        draw.text(
            (ring_center[0] - percent_width / 2, ring_center[1] - 68),
            percent_text,
            font=percent_font,
            fill="#48e1b5",
        )
        done_text = "完成" if completed >= total else phase
        done_font = cls._load_font(27, True)
        done_width = draw.textlength(done_text, font=done_font)
        draw.text(
            (ring_center[0] - done_width / 2, ring_center[1] + 54),
            done_text,
            font=done_font,
            fill="#48e1b5",
        )

        draw.text(
            (540, 178),
            f"已完成 {completed} 条 / 共 {total} 条",
            font=cls._load_font(30, True),
            fill="#f4fbf7",
        )

        statistics = [
            ("剩余任务", str(remaining), "条", "file", "#48e1b5"),
            ("提示词总数", str(total), "条", "stack", "#6ab7ff"),
        ]
        for index, (label, value, unit, icon, color) in enumerate(statistics):
            left = 530 + index * 318
            top = 250
            draw.rounded_rectangle(
                (left, top, left + 300, top + 154),
                radius=24,
                fill="#0a1a2a",
                outline="#1f3b51",
                width=1,
            )
            draw.ellipse(
                (left + 38, top + 42, left + 108, top + 112),
                fill="#102f39",
                outline="#1e6b6d",
                width=1,
            )
            cls._draw_icon(draw, left + 52, top + 56, icon, color, 42)
            draw.text(
                (left + 138, top + 42),
                label,
                font=label_font,
                fill="#b9c9d1",
            )
            draw.text(
                (left + 138, top + 84),
                value,
                font=number_font,
                fill=color,
            )
            value_width = draw.textlength(value, font=number_font)
            draw.text(
                (left + 152 + value_width, top + 110),
                unit,
                font=value_font,
                fill="#b9c9d1",
            )

        bar_left, bar_top = 56, 492
        bar_width, bar_height = width - 112, 24
        draw.text(
            (bar_left, bar_top - 44),
            "整体进度",
            font=value_font,
            fill="#dbe6df",
        )
        draw.rounded_rectangle(
            (
                bar_left,
                bar_top,
                bar_left + bar_width,
                bar_top + bar_height,
            ),
            radius=13,
            fill="#102032",
            outline="#1d4056",
            width=1,
        )
        if percent > 0:
            fill_width = max(bar_height, int(bar_width * percent / 100))
            draw.rounded_rectangle(
                (
                    bar_left,
                    bar_top,
                    bar_left + fill_width,
                    bar_top + bar_height,
                ),
                radius=13,
                fill="#48e1b5",
            )

        current_label = "刚刚完成" if phase == "已保存" else "当前任务"
        current_task = f"{os.path.basename(task.txt_path)} / 第 {task.prompt_index} 条"
        if completed >= scan.prompt_total:
            next_text = "全部任务已完成"
        elif task.global_index < scan.prompt_total:
            next_task = scan.tasks[task.global_index]
            next_text = (
                f"{os.path.basename(next_task.txt_path)} / "
                f"第 {next_task.prompt_index} 条"
            )
        else:
            next_text = "已是最后一条"

        current_text = cls._fit_middle_text(
            draw,
            current_task,
            current_font,
            430,
        )
        next_text = cls._fit_middle_text(draw, next_text, current_font, 430)

        info_top, info_height = 584, 122
        draw.rounded_rectangle(
            (56, info_top, width - 56, info_top + info_height),
            radius=22,
            fill="#0a1a2a",
            outline="#1f3b51",
            width=1,
        )
        draw.line(
            (width // 2, info_top + 28, width // 2, info_top + 94),
            fill="#1f3b51",
            width=1,
        )
        cls._draw_icon(draw, 92, info_top + 44, "file", "#48e1b5", 32)
        draw.text(
            (152, info_top + 28),
            current_label,
            font=label_font,
            fill="#9eb2bd",
        )
        draw.text(
            (152, info_top + 70),
            current_text,
            font=current_font,
            fill="#f4fbf7",
        )
        cls._draw_icon(
            draw,
            width // 2 + 50,
            info_top + 44,
            "file",
            "#6ab7ff",
            32,
        )
        draw.text(
            (width // 2 + 110, info_top + 28),
            "下一条",
            font=label_font,
            fill="#9eb2bd",
        )
        draw.text(
            (width // 2 + 110, info_top + 70),
            next_text,
            font=current_font,
            fill="#f4fbf7",
        )

        cls._draw_icon(draw, 56, 744, "folder", "#8295a2", 24)
        draw.text((94, 742), "路径", font=value_font, fill="#8295a2")
        path_text = cls._fit_text(
            draw,
            cls._path_tail(scan.source_path),
            value_font,
            900,
        )
        draw.text(
            (172, 742),
            path_text,
            font=value_font,
            fill="#9eb2bd",
        )

        array = np.asarray(image, dtype=np.float32) / 255.0
        return torch.from_numpy(array).unsqueeze(0)

    @staticmethod
    def _progress_preview_prefix(node_id: str | int | None) -> str:
        digest = hashlib.sha1(
            str(node_id or "global").encode("utf-8", errors="ignore")
        ).hexdigest()[:12]
        return f"lx_prompt_progress_{digest}_"

    @classmethod
    def _clear_progress_previews(cls, node_id: str | int | None) -> None:
        temp_root = _normalize_path(folder_paths.get_temp_directory())
        if not os.path.isdir(temp_root):
            return
        prefix = cls._progress_preview_prefix(node_id)
        for entry in os.scandir(temp_root):
            if (
                entry.is_file()
                and entry.name.startswith(prefix)
                and entry.name.casefold().endswith(".png")
            ):
                try:
                    os.remove(entry.path)
                except OSError:
                    pass

    @classmethod
    def _progress_preview_descriptor(
        cls,
        node_id: str | int | None,
        progress_image: torch.Tensor,
    ) -> Dict[str, str]:
        temp_root = _normalize_path(folder_paths.get_temp_directory())
        os.makedirs(temp_root, exist_ok=True)
        prefix = cls._progress_preview_prefix(node_id)
        filename = f"{prefix}{uuid.uuid4().hex[:12]}.png"
        destination = os.path.join(temp_root, filename)
        _tensor_to_pil(progress_image[0]).convert("RGB").save(
            destination,
            format="PNG",
            compress_level=1,
        )

        snapshots: List[Tuple[int, str]] = []
        for entry in os.scandir(temp_root):
            if (
                entry.is_file()
                and entry.name.startswith(prefix)
                and entry.name.casefold().endswith(".png")
            ):
                try:
                    snapshots.append((entry.stat().st_mtime_ns, entry.path))
                except OSError:
                    continue
        snapshots.sort(reverse=True)
        for _, old_path in snapshots[6:]:
            try:
                os.remove(old_path)
            except OSError:
                pass

        return {
            "filename": filename,
            "subfolder": "",
            "type": "temp",
        }

    @staticmethod
    def _emit_progress_update(
        node_id: str | int | None,
        descriptor: Dict[str, str],
        stats: str,
        completed: int,
        total: int,
        status: str,
    ) -> None:
        if node_id in (None, ""):
            return
        payload = {
            "node": str(node_id),
            "status": str(status),
            "completed": int(completed),
            "total": int(total),
            "stats": str(stats),
            "images": [descriptor],
        }
        try:
            from server import PromptServer

            instance = getattr(PromptServer, "instance", None)
            if instance is not None:
                instance.send_sync(
                    PROGRESS_EVENT,
                    payload,
                    getattr(instance, "client_id", None),
                )
        except Exception:
            pass

    @staticmethod
    def _linked_loader_ids(
        prompt: Any,
        saver_node_id: str | int | None,
    ) -> List[str]:
        if not isinstance(prompt, dict):
            return []

        saver_data = prompt.get(str(saver_node_id), prompt.get(saver_node_id))
        saver_inputs = saver_data.get("inputs") if isinstance(saver_data, dict) else {}
        direct_ids: List[str] = []
        if isinstance(saver_inputs, dict):
            for input_name in ("文件夹名称", "图片名称"):
                link = saver_inputs.get(input_name)
                if not isinstance(link, (list, tuple)) or len(link) < 2:
                    continue
                source_id = str(link[0])
                source_data = prompt.get(source_id, prompt.get(link[0]))
                if (
                    isinstance(source_data, dict)
                    and source_data.get("class_type") == "LXPromptBatch"
                ):
                    direct_ids.append(source_id)

        if direct_ids and len(set(direct_ids)) == 1:
            return [direct_ids[0]]

        return [
            str(node_id)
            for node_id, node_data in prompt.items()
            if isinstance(node_data, dict)
            and node_data.get("class_type") == "LXPromptBatch"
        ]

    @classmethod
    def _has_paired_saver(
        cls,
        prompt: Any,
        loader_node_id: str | int | None,
    ) -> bool:
        if not isinstance(prompt, dict):
            return False
        target_id = str(loader_node_id)
        for node_id, node_data in prompt.items():
            if (
                not isinstance(node_data, dict)
                or node_data.get("class_type") != "LXPromptBatchSaveImage"
            ):
                continue
            if target_id in cls._linked_loader_ids(prompt, node_id):
                return True
        return False

    @classmethod
    def commit_saved_task(
        cls,
        prompt: Any,
        saver_node_id: str | int | None,
        folder_name: str,
        image_name: str,
    ) -> Dict[str, Any] | None:
        for loader_id in cls._linked_loader_ids(prompt, saver_node_id):
            numeric_loader_id = int(loader_id) if loader_id.isdigit() else None
            loader_data = prompt.get(
                loader_id,
                prompt.get(numeric_loader_id) if numeric_loader_id is not None else None,
            )
            inputs = loader_data.get("inputs") if isinstance(loader_data, dict) else None
            if not isinstance(inputs, dict):
                continue

            read_mode = str(inputs.get("读取类型", READ_FOLDER))
            source_path = _normalize_path(str(inputs.get("路径", "")))
            sort_mode = str(inputs.get("文件排序", SORT_ASC))
            mode = str(inputs.get("模式", MODE_AUTO))
            if mode != MODE_AUTO:
                continue

            try:
                start_index = int(inputs.get("索引", 0))
                reset_version = int(inputs.get("重置版本", 0))
                scan = cls._build_scan(source_path, read_mode, sort_mode)
            except Exception:
                continue
            if scan.prompt_total <= 0:
                continue

            counter_key = cls._counter_key(
                loader_id,
                reset_version,
                read_mode,
                source_path,
                sort_mode,
            )
            task_index = cls._counter_value(counter_key, start_index)
            if task_index < 0 or task_index >= scan.prompt_total:
                continue

            task = scan.tasks[task_index]
            if (
                str(task.folder_name) != str(folder_name)
                or str(task.image_name) != str(image_name)
            ):
                continue

            with cls._lock:
                current = cls._counters.get(counter_key, task_index)
                if current != task_index:
                    return None
                cls._counters[counter_key] = task_index + 1

            completed = task_index + 1
            phase = "全部完成" if completed >= scan.prompt_total else "已保存"
            stats = cls._stats_text(
                scan,
                task,
                read_mode,
                sort_mode,
                completed_count=completed,
                phase=phase,
            )
            progress_image = cls._progress_image(
                scan,
                task,
                completed_count=completed,
                phase="已保存",
            )
            descriptor = cls._progress_preview_descriptor(loader_id, progress_image)
            cls._emit_progress_update(
                loader_id,
                descriptor,
                stats,
                completed,
                scan.prompt_total,
                "complete" if completed >= scan.prompt_total else "saved",
            )
            return {
                "loader_id": loader_id,
                "completed": completed,
                "total": scan.prompt_total,
                "descriptor": descriptor,
                "stats": stats,
            }
        return None

    def load_prompt(
        self,
        读取类型: str,
        路径: str,
        文件排序: str = SORT_ASC,
        模式: str = MODE_AUTO,
        索引: int = 0,
        重置版本: int = 0,
        unique_id: str | int | None = None,
        prompt: Any = None,
    ):
        source_path = _normalize_path(路径)
        scan = self._build_scan(source_path, 读取类型, 文件排序)

        if scan.txt_total == 0:
            raise ValueError("没有找到 TXT 文件。")
        if scan.prompt_total == 0:
            raise ValueError("TXT 中没有可用提示词；每个非空行才会计为一条提示词。")

        if 模式 == MODE_FIXED:
            task_index = int(索引)
            transactional = False
        else:
            counter_key = self._counter_key(
                unique_id,
                重置版本,
                读取类型,
                source_path,
                文件排序,
            )
            task_index = self._counter_value(counter_key, 索引)
            transactional = self._has_paired_saver(prompt, unique_id)
            with self._lock:
                self._counters.setdefault(counter_key, task_index)

        if task_index < 0:
            raise ValueError(f"索引不能小于0：{task_index}。")

        if task_index >= scan.prompt_total:
            if 模式 == MODE_FIXED:
                raise ValueError(
                    f"索引 {task_index} 超出有效范围0-{scan.prompt_total - 1}。"
                )

            task = scan.tasks[-1]
            stats = self._stats_text(
                scan,
                task,
                读取类型,
                文件排序,
                completed_count=scan.prompt_total,
                phase="全部完成",
            )
            progress_image = self._progress_image(
                scan,
                task,
                completed_count=scan.prompt_total,
                phase="已保存",
            )
            descriptor = self._progress_preview_descriptor(unique_id, progress_image)
            self._emit_progress_update(
                unique_id,
                descriptor,
                stats,
                scan.prompt_total,
                scan.prompt_total,
                "complete",
            )
            print(
                f"[LX加载提示词] 全部完成 {scan.prompt_total}/{scan.prompt_total}｜"
                "等待重置计数器"
            )
            return {
                "ui": {
                    PROGRESS_UI_KEY: [descriptor],
                    "lx_prompt_batch_status": [
                        {
                            "status": "complete",
                            "completed": scan.prompt_total,
                            "total": scan.prompt_total,
                        }
                    ],
                },
                "result": (
                    ExecutionBlocker(None),
                    task.folder_name,
                    task.image_name,
                    stats,
                    scan.prompt_total,
                    progress_image,
                    str(路径 or ""),
                ),
            }

        task = scan.tasks[task_index]
        completed = task_index if 模式 == MODE_AUTO else task.global_index
        phase = "处理中" if 模式 == MODE_AUTO else "固定索引"

        if 模式 == MODE_AUTO and not transactional:
            # 未连接配套保存节点时保留独立加载器的自动递增能力。
            with self._lock:
                self._counters[counter_key] = task_index + 1
            completed = task.global_index

        stats = self._stats_text(
            scan,
            task,
            读取类型,
            文件排序,
            completed_count=completed,
            phase=phase,
        )
        progress_image = self._progress_image(
            scan,
            task,
            completed_count=completed,
            phase=phase,
        )
        descriptor = self._progress_preview_descriptor(unique_id, progress_image)
        self._emit_progress_update(
            unique_id,
            descriptor,
            stats,
            completed,
            scan.prompt_total,
            "processing",
        )

        print(
            f"[LX加载提示词] 第 {task.global_index}/{task.prompt_total}｜"
            f"{task.folder_name}/{task.image_name}"
        )

        return {
            "ui": {
                PROGRESS_UI_KEY: [descriptor],
                "lx_prompt_batch_status": [
                    {
                        "status": "processing",
                        "completed": completed,
                        "total": scan.prompt_total,
                        "transactional": transactional,
                    }
                ],
            },
            "result": (
                task.prompt,
                task.folder_name,
                task.image_name,
                stats,
                scan.prompt_total,
                progress_image,
                str(路径 or ""),
            ),
        }


def _tensor_to_pil(image: torch.Tensor) -> Image.Image:
    array = image.detach().cpu().numpy()
    if array.ndim == 4:
        array = array[0]
    array = np.nan_to_num(array, nan=0.0, posinf=1.0, neginf=0.0)
    if array.size and float(np.max(array)) > 1.001:
        array = array / 255.0
    array = np.clip(array, 0.0, 1.0)
    array = np.rint(array * 255.0).astype(np.uint8)

    if array.ndim == 2:
        return Image.fromarray(array, mode="L")
    if array.shape[-1] == 1:
        return Image.fromarray(array[..., 0], mode="L")
    if array.shape[-1] == 2:
        return Image.fromarray(array, mode="LA")
    if array.shape[-1] >= 4:
        return Image.fromarray(array[..., :4], mode="RGBA")
    return Image.fromarray(array[..., :3], mode="RGB")


def _png_metadata(prompt: Any, extra_pnginfo: Any) -> PngInfo | None:
    if prompt is None and not extra_pnginfo:
        return None

    metadata = PngInfo()
    if prompt is not None:
        metadata.add_text("prompt", json.dumps(prompt, ensure_ascii=False))
    if isinstance(extra_pnginfo, dict):
        for key, value in extra_pnginfo.items():
            metadata.add_text(str(key), json.dumps(value, ensure_ascii=False))
    return metadata


def _within_root(path: str, root: str) -> bool:
    try:
        common = os.path.commonpath(
            [
                os.path.abspath(os.path.normpath(path)),
                os.path.abspath(os.path.normpath(root)),
            ]
        )
    except ValueError:
        return False
    return os.path.normcase(common) == os.path.normcase(os.path.abspath(os.path.normpath(root)))


class LXPromptBatchSaveImage:
    """Save generated images into the folder named by the current TXT series."""

    DESCRIPTION = "与“加载提示词（TXT系列）”配套，按 TXT 名称和提示词序号保存图片。"
    SEARCH_ALIASES = [
        "lx",
        "LX",
        "灵犀",
        "提示词系列保存",
        "系列文件夹保存",
        "save prompt series",
        "prompt batch save",
    ]
    CATEGORY = CATEGORY
    FUNCTION = "save_images"
    RETURN_TYPES = ("IMAGE",)
    RETURN_NAMES = ("图像",)
    OUTPUT_NODE = True

    _save_lock = threading.RLock()

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "图像": ("IMAGE",),
                "文件夹名称": (
                    "STRING",
                    {
                        "default": "",
                        "forceInput": True,
                        "tooltip": "连接“加载提示词（TXT系列）”的文件夹名称输出。",
                    },
                ),
                "图片名称": (
                    "STRING",
                    {
                        "default": "",
                        "forceInput": True,
                        "tooltip": "连接“加载提示词（TXT系列）”的图片名称输出。",
                    },
                ),
                "保存路径": (
                    "STRING",
                    {
                        "default": "",
                        "multiline": False,
                        "placeholder": "留空 = ComfyUI 默认输出目录",
                        "tooltip": (
                            "留空保存到 ComfyUI/output；相对路径位于 output 下；"
                            "也支持填写绝对路径。"
                        ),
                    },
                ),
                "文件名前缀": (
                    "STRING",
                    {
                        "default": "",
                        "multiline": False,
                        "placeholder": "例如 AI_",
                    },
                ),
                "文件名后缀": (
                    "STRING",
                    {
                        "default": "",
                        "multiline": False,
                        "placeholder": "例如 _v1",
                    },
                ),
                "保存格式": (SAVE_FORMATS, {"default": "PNG"}),
                "图像质量": (
                    "INT",
                    {
                        "default": 95,
                        "min": 1,
                        "max": 100,
                        "step": 1,
                        "tooltip": "仅对 JPG 和 WEBP 生效；PNG 忽略此参数。",
                    },
                ),
                "同名追加后缀": (
                    "BOOLEAN",
                    {
                        "default": False,
                        "label_on": "追加",
                        "label_off": "覆盖",
                        "tooltip": "追加：同名时生成 -1、-2……；覆盖：直接替换同名文件。",
                    },
                ),
                "显示预览": (
                    "BOOLEAN",
                    {
                        "default": True,
                        "label_on": "显示",
                        "label_off": "关闭",
                    },
                ),
            },
            "hidden": {
                "prompt": "PROMPT",
                "extra_pnginfo": "EXTRA_PNGINFO",
                "unique_id": "UNIQUE_ID",
            },
        }

    @classmethod
    def IS_CHANGED(cls, **_kwargs):
        return float("nan")

    @staticmethod
    def _save_root(value: str) -> Tuple[str, str]:
        output_root = _normalize_path(folder_paths.get_output_directory())
        raw = _unwrap_path(value)
        if not raw:
            return output_root, output_root
        expanded = os.path.expandvars(os.path.expanduser(raw))
        save_root = (
            os.path.abspath(os.path.normpath(expanded))
            if os.path.isabs(expanded)
            else os.path.abspath(os.path.normpath(os.path.join(output_root, expanded)))
        )
        return output_root, save_root

    @staticmethod
    def _unique_path(dest_dir: str, stem: str, extension: str, append: bool) -> str:
        candidate = os.path.join(dest_dir, f"{stem}{extension}")
        if not append or not os.path.exists(candidate):
            return candidate

        suffix = 1
        while True:
            candidate = os.path.join(dest_dir, f"{stem}-{suffix}{extension}")
            if not os.path.exists(candidate):
                return candidate
            suffix += 1

    @staticmethod
    def _save_atomic(
        pil_image: Image.Image,
        destination: str,
        save_format: str,
        quality: int,
        prompt: Any,
        extra_pnginfo: Any,
    ) -> None:
        temp_path = os.path.join(
            os.path.dirname(destination),
            f".{os.path.basename(destination)}.{uuid.uuid4().hex}.tmp",
        )
        try:
            if save_format == "PNG":
                pil_image.save(
                    temp_path,
                    format="PNG",
                    compress_level=4,
                    pnginfo=_png_metadata(prompt, extra_pnginfo),
                )
            elif save_format == "JPG":
                pil_image.convert("RGB").save(
                    temp_path,
                    format="JPEG",
                    quality=max(1, min(100, int(quality))),
                    optimize=True,
                    subsampling=1,
                )
            else:
                webp_image = pil_image if pil_image.mode in {"RGB", "RGBA"} else pil_image.convert("RGB")
                webp_image.save(
                    temp_path,
                    format="WEBP",
                    quality=max(1, min(100, int(quality))),
                    method=4,
                )
            os.replace(temp_path, destination)
        finally:
            if os.path.exists(temp_path):
                try:
                    os.remove(temp_path)
                except OSError:
                    pass

    @staticmethod
    def _preview_descriptor(path: str, output_root: str) -> Dict[str, str]:
        if _within_root(path, output_root):
            subfolder = os.path.relpath(os.path.dirname(path), output_root)
            if subfolder == ".":
                subfolder = ""
            return {
                "filename": os.path.basename(path),
                "subfolder": subfolder.replace("\\", "/"),
                "type": "output",
            }

        temp_root = _normalize_path(folder_paths.get_temp_directory())
        os.makedirs(temp_root, exist_ok=True)
        stat = os.stat(path)
        digest = hashlib.sha1(
            f"{os.path.abspath(path)}|{stat.st_mtime_ns}|{stat.st_size}".encode(
                "utf-8",
                errors="ignore",
            )
        ).hexdigest()[:12]
        preview_name = f"lx_prompt_save_{digest}.png"
        preview_path = os.path.join(temp_root, preview_name)
        if not os.path.isfile(preview_path):
            with Image.open(path) as image:
                image.convert("RGB").save(preview_path, format="PNG", compress_level=1)
        return {
            "filename": preview_name,
            "subfolder": "",
            "type": "temp",
        }

    def save_images(
        self,
        图像: torch.Tensor,
        文件夹名称: str,
        图片名称: str,
        保存路径: str = "",
        文件名前缀: str = "",
        文件名后缀: str = "",
        保存格式: str = "PNG",
        图像质量: int = 95,
        同名追加后缀: bool = False,
        显示预览: bool = True,
        prompt: Any = None,
        extra_pnginfo: Any = None,
        unique_id: str | int | None = None,
    ):
        if 图像 is None or not hasattr(图像, "shape") or int(图像.shape[0]) <= 0:
            raise ValueError("没有可保存的图像。")

        save_format = str(保存格式 or "PNG").upper()
        if save_format not in FORMAT_EXTENSIONS:
            raise ValueError(f"不支持的保存格式：{保存格式}")

        output_root, save_root = self._save_root(保存路径)
        folder_name = _sanitize_component(文件夹名称, "未命名系列")
        image_name = os.path.splitext(
            _sanitize_component(os.path.basename(str(图片名称 or "")), "001")
        )[0]
        prefix = _sanitize_affix(文件名前缀)
        suffix = _sanitize_affix(文件名后缀)
        destination_dir = os.path.join(save_root, folder_name)
        os.makedirs(destination_dir, exist_ok=True)

        extension = FORMAT_EXTENSIONS[save_format]
        batch_size = int(图像.shape[0])
        saved_paths: List[str] = []
        previews: List[Dict[str, str]] = []

        for batch_index in range(batch_size):
            batch_name = image_name
            if batch_size > 1:
                batch_name = f"{image_name}-{batch_index + 1:02d}"
            final_stem = _sanitize_component(
                f"{prefix}{batch_name}{suffix}",
                f"image-{batch_index + 1:03d}",
                limit=220,
            )
            pil_image = _tensor_to_pil(图像[batch_index])

            with self._save_lock:
                destination = self._unique_path(
                    destination_dir,
                    final_stem,
                    extension,
                    bool(同名追加后缀),
                )
                self._save_atomic(
                    pil_image,
                    destination,
                    save_format,
                    图像质量,
                    prompt,
                    extra_pnginfo,
                )

            saved_paths.append(destination)
            if 显示预览:
                previews.append(self._preview_descriptor(destination, output_root))

        progress_commit = LXPromptBatchLoader.commit_saved_task(
            prompt,
            unique_id,
            str(文件夹名称),
            str(图片名称),
        )

        print(
            f"[LX保存提示词系列] 已保存 {len(saved_paths)} 张｜"
            f"{saved_paths[-1] if saved_paths else destination_dir}"
        )

        return {
            "ui": {
                "images": previews,
                "text": saved_paths,
                "lx_prompt_save": [
                    {
                        "folder": folder_name,
                        "count": len(saved_paths),
                        "path": saved_paths[-1] if saved_paths else destination_dir,
                    }
                ],
                "lx_prompt_batch_commit": [progress_commit] if progress_commit else [],
            },
            "result": (图像,),
        }


def register_prompt_batch_routes() -> bool:
    try:
        from aiohttp import web
        from server import PromptServer
    except Exception as exc:
        print(f"[LX加载提示词] 无法注册计数器重置接口：{exc}")
        return False

    instance = getattr(PromptServer, "instance", None)
    if instance is None:
        return False
    marker = "_lx_prompt_batch_routes_installed"
    if getattr(instance, marker, False):
        return True
    setattr(instance, marker, True)

    @instance.routes.post("/lx/prompt_batch/reset")
    async def reset_prompt_batch_counter(request):
        try:
            data = await request.json() if request.can_read_body else {}
        except Exception:
            return web.json_response(
                {"success": False, "message": "无效的重置请求。"},
                status=400,
            )

        node_id = str(data.get("node_id", "")).strip()
        if not node_id:
            return web.json_response(
                {"success": False, "message": "缺少节点ID。"},
                status=400,
            )

        removed = LXPromptBatchLoader.reset_counter(node_id)
        try:
            instance.send_sync(
                PROGRESS_EVENT,
                {
                    "node": node_id,
                    "status": "reset",
                    "completed": 0,
                    "total": 0,
                    "stats": "",
                    "images": [],
                },
                getattr(instance, "client_id", None),
            )
        except Exception:
            pass
        return web.json_response(
            {
                "success": True,
                "node_id": node_id,
                "removed": removed,
                "message": "计数器已重置，下次从第1条开始。",
            }
        )

    return True


NODE_CLASS_MAPPINGS = {
    "LXPromptBatch": LXPromptBatchLoader,
    "LXPromptBatchSaveImage": LXPromptBatchSaveImage,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "LXPromptBatch": "加载提示词（TXT系列）",
    "LXPromptBatchSaveImage": "保存图像（TXT系列）",
}
