# -*- coding: utf-8 -*-
from __future__ import annotations

import hashlib
import itertools
import json
import os
import re
from typing import Any

import numpy as np
import torch
from PIL import Image, ImageDraw, ImageFont, ImageOps

try:
    import folder_paths  # type: ignore[reportMissingImports]
except Exception:  # pragma: no cover - ComfyUI provides this at runtime.
    folder_paths = None


FOLDER_BATCH_TASKS_TYPE = "LX_FOLDER_BATCH_TASKS"
FOLDER_BATCH_PAYLOAD_TYPE = "lx_folder_batch_tasks"
IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff")
SAVE_FORMATS = ["PNG", "JPG", "WEBP"]
PAIR_MODE_SAME_NAME = "同名匹配"
PAIR_MODE_END_NUMBER = "末尾编号匹配"
PAIR_MODE_TRIM_SUFFIX = "去尾序号匹配"
PAIR_MODE_SEQUENCE = "顺序匹配"
PAIR_MODE_PRODUCT = "全部组合"
PAIR_MODES = [
    PAIR_MODE_SAME_NAME,
    PAIR_MODE_END_NUMBER,
    PAIR_MODE_TRIM_SUFFIX,
    PAIR_MODE_SEQUENCE,
    PAIR_MODE_PRODUCT,
]
PAIR_MODE_ALIASES = {
    "交叉组合": PAIR_MODE_PRODUCT,
    "全量组合": PAIR_MODE_PRODUCT,
    "两两组合": PAIR_MODE_PRODUCT,
}
HARD_TASK_LIMIT = 20000
PREVIEW_CELL_SIZE = 800
PREVIEW_LABEL_HEIGHT = 76
PREVIEW_GAP = 10
COMPARE_MAX_REFS = 4


def clean_str(value: object) -> str:
    return "" if value is None else str(value).strip()


def clip(value: object, limit: int = 500) -> str:
    text = "" if value is None else str(value)
    return text if len(text) <= limit else text[:limit] + "..."


def sha_json(data: object) -> str:
    raw = json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8", errors="replace")).hexdigest()


def _unwrap_quoted_path(value: object) -> str:
    text = clean_str(value)
    if len(text) >= 2 and text[0] == text[-1] and text[0] in {"'", '"'}:
        text = text[1:-1].strip()
    return text


def normalize_dir(value: object, *, default_output: bool = False) -> str:
    text = _unwrap_quoted_path(value)
    if not text and default_output:
        base = folder_paths.get_output_directory() if folder_paths is not None else os.getcwd()
        text = os.path.join(base, "lingxi_folder_batch")
    text = os.path.expandvars(os.path.expanduser(text))
    return os.path.abspath(os.path.normpath(text)) if text else ""


def natural_key(value: object) -> list[Any]:
    text = str(value or "").replace("\\", "/").casefold()
    parts = re.split(r"(\d+)", text)
    return [int(part) if part.isdigit() else part for part in parts]


def scan_images(folder: object, include_subfolders: bool) -> tuple[str, list[dict[str, str]], str]:
    root = normalize_dir(folder)
    if not root:
        return "", [], "文件夹路径为空。"
    if not os.path.isdir(root):
        return root, [], f"文件夹不存在：{root}"

    records: list[dict[str, str]] = []

    def add_file(abs_path: str) -> None:
        ext = os.path.splitext(abs_path)[1].lower()
        if ext not in IMAGE_EXTS:
            return
        try:
            rel_path = os.path.relpath(abs_path, root).replace("\\", "/")
        except ValueError:
            rel_path = os.path.basename(abs_path)
        rel_dir = os.path.dirname(rel_path).replace("\\", "/")
        name = os.path.basename(abs_path)
        stem, ext = os.path.splitext(name)
        rel_stem = os.path.splitext(rel_path)[0].replace("\\", "/")
        records.append(
            {
                "path": os.path.abspath(os.path.normpath(abs_path)),
                "rel_path": rel_path,
                "rel_dir": rel_dir,
                "name": name,
                "stem": stem,
                "rel_stem": rel_stem,
                "ext": ext.lower(),
            }
        )

    if include_subfolders:
        for current, dirs, files in os.walk(root):
            dirs[:] = sorted([item for item in dirs if not item.startswith(".")], key=natural_key)
            for name in sorted([item for item in files if not item.startswith(".")], key=natural_key):
                add_file(os.path.join(current, name))
    else:
        try:
            names = sorted(os.listdir(root), key=natural_key)
        except OSError as exc:
            return root, [], f"读取文件夹失败：{exc}"
        for name in names:
            if name.startswith("."):
                continue
            abs_path = os.path.join(root, name)
            if os.path.isfile(abs_path):
                add_file(abs_path)

    records.sort(key=lambda item: natural_key(item.get("rel_path", "")))
    return root, records, ""


def save_extension(save_format: object) -> str:
    fmt = clean_str(save_format).upper()
    if fmt in {"JPG", "JPEG"}:
        return ".jpg"
    if fmt == "WEBP":
        return ".webp"
    return ".png"


def _safe_component(value: object) -> str:
    text = clean_str(value)
    invalid = '<>:"\\|?*'
    safe = "".join("_" if ch in invalid or ord(ch) < 32 else ch for ch in text)
    safe = safe.strip().rstrip(".")
    return safe or "item"


def safe_rel_stem(value: object) -> str:
    text = clean_str(value).replace("\\", "/").strip("/")
    parts = [_safe_component(part) for part in text.split("/") if part not in {"", ".", ".."}]
    return "/".join(parts) if parts else "item"


def unique_short_hash(value: object) -> str:
    text = "" if value is None else str(value)
    return hashlib.sha1(text.encode("utf-8", errors="replace")).hexdigest()[:10]


def shorten_filename_stem(stem: str, limit: int = 150) -> str:
    if len(stem) <= limit:
        return stem
    return f"{stem[: limit - 13]}_{unique_short_hash(stem)}"


def _rel_path_key(rel_path: str) -> str:
    return rel_path.replace("\\", "/").casefold()


def output_path(
    output_root: str,
    rel_stem: object,
    save_format: object,
    *,
    used_rel_paths: set[str] | None = None,
    uniqueness_value: object | None = None,
) -> tuple[str, str]:
    output_root = os.path.abspath(os.path.normpath(output_root))
    rel = safe_rel_stem(rel_stem)
    parts = rel.split("/")
    parts[-1] = shorten_filename_stem(parts[-1])
    ext = save_extension(save_format)
    rel_path = "/".join(parts) + ext
    if used_rel_paths is not None:
        key = _rel_path_key(rel_path)
        if key in used_rel_paths:
            base_part = parts[-1]
            suffix = unique_short_hash(uniqueness_value if uniqueness_value is not None else rel_stem)
            counter = 1
            while key in used_rel_paths:
                extra = suffix if counter == 1 else f"{suffix}_{counter}"
                candidate_parts = list(parts)
                candidate_parts[-1] = shorten_filename_stem(f"{base_part}_{extra}")
                rel_path = "/".join(candidate_parts) + ext
                key = _rel_path_key(rel_path)
                counter += 1
        used_rel_paths.add(key)
    abs_path = os.path.abspath(os.path.normpath(os.path.join(output_root, *rel_path.split("/"))))
    try:
        common = os.path.commonpath([output_root, abs_path])
    except ValueError:
        common = ""
    if os.path.normcase(common) != os.path.normcase(output_root):
        raise ValueError("输出路径非法，不能跳出输出文件夹。")
    return abs_path, rel_path


def task_payload(tasks: list[dict[str, Any]], meta: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "type": FOLDER_BATCH_PAYLOAD_TYPE,
        "version": 1,
        "tasks": tasks,
        "meta": meta or {},
    }


def normalize_tasks(value: object) -> list[dict[str, Any]]:
    if isinstance(value, dict) and value.get("type") == FOLDER_BATCH_PAYLOAD_TYPE:
        raw = value.get("tasks", [])
    elif isinstance(value, list):
        raw = value
    else:
        raw = []
    return [item for item in raw if isinstance(item, dict)]


def payload_meta(value: object) -> dict[str, Any]:
    if isinstance(value, dict) and value.get("type") == FOLDER_BATCH_PAYLOAD_TYPE:
        meta = value.get("meta", {})
        return meta if isinstance(meta, dict) else {}
    return {}


def normalize_pair_mode(value: object) -> str:
    text = clean_str(value) or PAIR_MODE_SAME_NAME
    text = PAIR_MODE_ALIASES.get(text, text)
    return text if text in PAIR_MODES else PAIR_MODE_SAME_NAME


def _scope_key(record: dict[str, str], key: str, include_subfolders: bool) -> str:
    rel_dir = record.get("rel_dir", "") if include_subfolders else ""
    return f"{rel_dir}/{key}".strip("/").casefold()


def image_match_key(record: dict[str, str], pair_mode: str, include_subfolders: bool) -> str:
    pair_mode = normalize_pair_mode(pair_mode)
    stem = record.get("stem", "").strip()

    if pair_mode == PAIR_MODE_END_NUMBER:
        match = re.search(r"(?:[\s_-]+)?(\d+)$", stem)
        if not match:
            return ""
        return _scope_key(record, match.group(1), include_subfolders)

    if pair_mode == PAIR_MODE_TRIM_SUFFIX:
        source = record.get("rel_stem", "") if include_subfolders else stem
        key = re.sub(r"[\s_-]+\d+$", "", source.strip())
        key = key.replace("\\", "/").strip("/ _-")
        return key.casefold()

    if include_subfolders:
        return record.get("rel_stem", "").replace("\\", "/").strip("/").casefold()
    return record.get("stem", "").casefold()


def build_unique_key_map(
    records: list[dict[str, str]],
    pair_mode: str,
    include_subfolders: bool,
) -> tuple[dict[str, dict[str, str]], dict[str, list[dict[str, str]]], list[dict[str, str]]]:
    buckets: dict[str, list[dict[str, str]]] = {}
    no_key: list[dict[str, str]] = []
    for record in records:
        key = image_match_key(record, pair_mode, include_subfolders)
        if not key:
            no_key.append(record)
            continue
        buckets.setdefault(key, []).append(record)
    unique = {key: items[0] for key, items in buckets.items() if len(items) == 1}
    duplicates = {key: items for key, items in buckets.items() if len(items) > 1}
    return unique, duplicates, no_key


def build_matched_groups(
    sources: list[dict[str, Any]],
    pair_mode: str,
    include_subfolders: bool,
) -> tuple[list[tuple[str, list[dict[str, str]]]], dict[str, Any]]:
    pair_mode = normalize_pair_mode(pair_mode)
    maps: list[dict[str, dict[str, str]]] = []
    duplicates_by_source: list[dict[str, list[dict[str, str]]]] = []
    no_key_by_source: list[list[dict[str, str]]] = []
    for source in sources:
        unique, duplicates, no_key = build_unique_key_map(source["records"], pair_mode, include_subfolders)
        maps.append(unique)
        duplicates_by_source.append(duplicates)
        no_key_by_source.append(no_key)

    if not maps:
        return [], {"unmatched": [], "duplicates": [], "no_key": []}

    common = set(maps[0])
    for current in maps[1:]:
        common &= set(current)

    groups = [(key, [current[key] for current in maps]) for key in sorted(common, key=natural_key)]

    unmatched: list[dict[str, Any]] = []
    duplicates: list[dict[str, Any]] = []
    no_key_items: list[dict[str, Any]] = []
    for index, source in enumerate(sources, start=1):
        source_name = f"图{index}"
        for record in source["records"]:
            key = image_match_key(record, pair_mode, include_subfolders)
            if not key:
                continue
            if key in common and key not in duplicates_by_source[index - 1]:
                continue
            if key not in duplicates_by_source[index - 1]:
                unmatched.append({"source": source_name, "rel_path": record.get("rel_path", ""), "key": key})
        for key, items in duplicates_by_source[index - 1].items():
            duplicates.append(
                {
                    "source": source_name,
                    "key": key,
                    "items": [item.get("rel_path", "") for item in items],
                }
            )
        for record in no_key_by_source[index - 1]:
            no_key_items.append({"source": source_name, "rel_path": record.get("rel_path", "")})

    detail = {
        "unmatched": unmatched,
        "duplicates": duplicates,
        "no_key": no_key_items,
        "common_count": len(common),
    }
    return groups, detail


def build_sequence_groups(
    sources: list[dict[str, Any]],
) -> tuple[list[tuple[str, list[dict[str, str]]]], dict[str, Any]]:
    if not sources:
        return [], {"unmatched": [], "duplicates": [], "no_key": [], "common_count": 0}

    count = min(len(source["records"]) for source in sources)
    groups: list[tuple[str, list[dict[str, str]]]] = []
    for offset in range(count):
        records = [source["records"][offset] for source in sources]
        key = records[0].get("rel_stem", "") or records[0].get("stem", "") or f"顺序{offset + 1}"
        groups.append((key, records))

    unmatched: list[dict[str, Any]] = []
    for source_index, source in enumerate(sources, start=1):
        source_name = f"图{source_index}"
        for offset, record in enumerate(source["records"][count:], start=count + 1):
            unmatched.append({
                "source": source_name,
                "rel_path": record.get("rel_path", ""),
                "key": f"第{offset}张",
            })

    return groups, {
        "unmatched": unmatched,
        "duplicates": [],
        "no_key": [],
        "common_count": count,
        "sequence_count": count,
    }


def iter_product_groups(
    sources: list[dict[str, Any]],
    limit: int,
) -> tuple[list[tuple[str, list[dict[str, str]]]], int, bool]:
    counts = [len(source["records"]) for source in sources]
    total = 1
    for count in counts:
        total *= count
    effective_limit = limit if limit > 0 else min(total, HARD_TASK_LIMIT)
    capped = limit <= 0 and total > HARD_TASK_LIMIT
    groups: list[tuple[str, list[dict[str, str]]]] = []
    for items in itertools.islice(itertools.product(*[source["records"] for source in sources]), effective_limit):
        key = "__".join(safe_rel_stem(item.get("rel_stem", "")).replace("/", "_") for item in items)
        groups.append((shorten_filename_stem(key, 180), list(items)))
    return groups, total, capped


def make_task(
    *,
    prompt: str,
    image_records: list[dict[str, str]],
    output_root: str,
    output_rel_stem: str,
    save_format: str,
    ratio: str,
    size: str,
    quality: str,
    moderation: str,
    task_name: str,
    source_count: int,
    used_output_rel_paths: set[str] | None = None,
) -> dict[str, Any]:
    image_paths = [record["path"] for record in image_records]
    image_rel_paths = [record["rel_path"] for record in image_records]
    abs_output, rel_output = output_path(
        output_root,
        output_rel_stem,
        save_format,
        used_rel_paths=used_output_rel_paths,
        uniqueness_value={
            "rel_stem": output_rel_stem,
            "images": image_rel_paths,
            "task_name": task_name,
        },
    )
    task_id = sha_json(
        {
            "prompt": prompt,
            "images": image_rel_paths,
            "output": rel_output,
            "ratio": ratio,
            "size": size,
            "quality": quality,
            "moderation": moderation,
        }
    )[:24]
    return {
        "type": "lx_folder_batch_task",
        "version": 1,
        "task_id": task_id,
        "name": task_name,
        "prompt": prompt,
        "image_paths": image_paths,
        "image_rel_paths": image_rel_paths,
        "output_path": abs_output,
        "output_rel_path": rel_output,
        "output_root": output_root,
        "save_format": save_format,
        "ratio": ratio,
        "size": size,
        "quality": quality,
        "moderation": moderation,
        "source_count": source_count,
    }


def preview_lines(title: str, lines: list[str], limit: int = 30) -> str:
    output = [title]
    if not lines:
        output.append("无任务。")
        return "\n".join(output)
    output.extend(lines[:limit])
    if len(lines) > limit:
        output.append(f"... 还有 {len(lines) - limit} 行")
    return "\n".join(output)


def pil_to_tensor(image: Image.Image) -> torch.Tensor:
    arr = np.asarray(image.convert("RGB")).astype(np.float32) / 255.0
    return torch.from_numpy(arr[None, ...])


def image_batch(images: list[Image.Image], fallback_size: tuple[int, int] = (640, 360)) -> torch.Tensor:
    if not images:
        return pil_to_tensor(blank_preview("暂无预览", fallback_size))
    width = max(max(1, image.width) for image in images)
    height = max(max(1, image.height) for image in images)
    tensors = []
    for image in images:
        rgb = image.convert("RGB")
        canvas = Image.new("RGB", (width, height), (245, 245, 245))
        x = max(0, (width - rgb.width) // 2)
        y = max(0, (height - rgb.height) // 2)
        canvas.paste(rgb, (x, y))
        tensors.append(pil_to_tensor(canvas))
    return torch.cat(tensors, dim=0)


def _font(size: int, bold: bool = False):
    candidates = [
        r"C:\Windows\Fonts\msyhbd.ttc" if bold else r"C:\Windows\Fonts\msyh.ttc",
        r"C:\Windows\Fonts\simhei.ttf",
        r"C:\Windows\Fonts\arialbd.ttf" if bold else r"C:\Windows\Fonts\arial.ttf",
    ]
    for path in candidates:
        try:
            if path and os.path.exists(path):
                return ImageFont.truetype(path, size=size)
        except Exception:
            pass
    return ImageFont.load_default()


def _fit_text(draw: ImageDraw.ImageDraw, text: object, font, max_width: int) -> str:
    value = str(text or "")
    try:
        if draw.textlength(value, font=font) <= max_width:
            return value
        out = value
        while len(out) > 1 and draw.textlength(out + "...", font=font) > max_width:
            out = out[:-1]
        return out + "..."
    except Exception:
        return value[:24] + ("..." if len(value) > 24 else "")


def _draw_centered_label(
    draw: ImageDraw.ImageDraw,
    box: tuple[int, int, int, int],
    text: object,
    font,
    fill: tuple[int, int, int],
) -> None:
    x1, y1, x2, y2 = box
    label = _fit_text(draw, text, font, max(1, x2 - x1))
    bbox = draw.textbbox((0, 0), label, font=font)
    text_h = bbox[3] - bbox[1]
    y = y1 + max(0, (y2 - y1 - text_h) // 2) - bbox[1]
    draw.text((x1, y), label, fill=fill, font=font)


def blank_preview(text: str, size: tuple[int, int] = (640, 360)) -> Image.Image:
    width, height = size
    image = Image.new("RGB", (max(64, width), max(64, height)), (245, 245, 245))
    draw = ImageDraw.Draw(image)
    font = _font(26, True)
    label = _fit_text(draw, text, font, image.width - 40)
    bbox = draw.textbbox((0, 0), label, font=font)
    x = (image.width - (bbox[2] - bbox[0])) // 2
    y = (image.height - (bbox[3] - bbox[1])) // 2
    draw.text((x, y), label, fill=(90, 96, 108), font=font)
    return image


def _load_pil(path: str) -> Image.Image:
    with Image.open(path) as image:
        return ImageOps.exif_transpose(image).convert("RGB")


def _fit_on_cell(image: Image.Image, cell_size: int) -> Image.Image:
    source = image.convert("RGB")
    width, height = source.size
    if width <= 0 or height <= 0:
        return Image.new("RGB", (cell_size, cell_size), (255, 255, 255))
    scale = min(cell_size / width, cell_size / height)
    next_size = (max(1, int(round(width * scale))), max(1, int(round(height * scale))))
    resized = source.resize(next_size, Image.LANCZOS)
    cell = Image.new("RGB", (cell_size, cell_size), (255, 255, 255))
    x = (cell_size - resized.width) // 2
    y = (cell_size - resized.height) // 2
    cell.paste(resized, (x, y))
    return cell


def make_collage(
    image_paths: list[str],
    labels: list[str] | None = None,
    result_image: Image.Image | None = None,
    result_label: str = "结果",
    cell_size: int = PREVIEW_CELL_SIZE,
) -> Image.Image:
    entries: list[tuple[str, Image.Image]] = []
    labels = labels or []
    for index, path in enumerate(image_paths, start=1):
        label = labels[index - 1] if index - 1 < len(labels) and labels[index - 1] else f"图{index}"
        try:
            entries.append((label, _load_pil(path)))
        except Exception:
            entries.append((label, blank_preview("加载失败", (cell_size, cell_size))))
    if result_image is not None:
        entries.append((result_label, result_image.convert("RGB")))
    if not entries:
        return blank_preview("暂无预览")

    count = len(entries)
    width = PREVIEW_GAP + count * cell_size + (count - 1) * PREVIEW_GAP + PREVIEW_GAP
    height = PREVIEW_GAP + PREVIEW_LABEL_HEIGHT + cell_size + PREVIEW_GAP
    canvas = Image.new("RGB", (width, height), (238, 241, 245))
    draw = ImageDraw.Draw(canvas)
    font = _font(max(17, int(round(cell_size * 0.05))), True)
    x = PREVIEW_GAP
    for label, image in entries:
        draw.rounded_rectangle(
            (x - 1, PREVIEW_GAP - 1, x + cell_size + 1, PREVIEW_GAP + PREVIEW_LABEL_HEIGHT + cell_size + 1),
            radius=6,
            fill=(250, 250, 250),
            outline=(215, 221, 230),
            width=1,
        )
        _draw_centered_label(
            draw,
            (x + 8, PREVIEW_GAP, x + cell_size - 8, PREVIEW_GAP + PREVIEW_LABEL_HEIGHT),
            label,
            font,
            (52, 64, 84),
        )
        cell = _fit_on_cell(image, cell_size)
        canvas.paste(cell, (x, PREVIEW_GAP + PREVIEW_LABEL_HEIGHT))
        x += cell_size + PREVIEW_GAP
    return canvas


def make_single_task_preview(
    image_path: str,
    task_label: str,
    file_label: str,
    cell_size: int = PREVIEW_CELL_SIZE,
) -> Image.Image:
    header_height = PREVIEW_LABEL_HEIGHT
    footer_height = PREVIEW_LABEL_HEIGHT
    width = PREVIEW_GAP * 2 + cell_size
    height = PREVIEW_GAP + header_height + cell_size + footer_height + PREVIEW_GAP
    canvas = Image.new("RGB", (width, height), (238, 241, 245))
    draw = ImageDraw.Draw(canvas)
    title_font = _font(max(18, int(round(cell_size * 0.06))), True)
    file_font = _font(max(15, int(round(cell_size * 0.04))), False)

    draw.rounded_rectangle(
        (PREVIEW_GAP - 1, PREVIEW_GAP - 1, PREVIEW_GAP + cell_size + 1, height - PREVIEW_GAP + 1),
        radius=6,
        fill=(250, 250, 250),
        outline=(215, 221, 230),
        width=1,
    )
    _draw_centered_label(
        draw,
        (PREVIEW_GAP + 8, PREVIEW_GAP, PREVIEW_GAP + cell_size - 8, PREVIEW_GAP + header_height),
        task_label,
        title_font,
        (52, 64, 84),
    )

    try:
        source = _load_pil(image_path)
    except Exception:
        source = blank_preview("加载失败", (cell_size, cell_size))
    cell = _fit_on_cell(source, cell_size)
    canvas.paste(cell, (PREVIEW_GAP, PREVIEW_GAP + header_height))

    _draw_centered_label(
        draw,
        (
            PREVIEW_GAP + 8,
            PREVIEW_GAP + header_height + cell_size,
            PREVIEW_GAP + cell_size - 8,
            PREVIEW_GAP + header_height + cell_size + footer_height,
        ),
        file_label,
        file_font,
        (88, 99, 115),
    )
    return canvas


def _compare_unit(result_size: tuple[int, int]) -> tuple[int, int, int]:
    base = max(1, max(result_size))
    gap = max(18, min(48, int(round(base * 0.012))))
    header = max(42, min(76, int(round(base * 0.018))))
    outer = gap
    return gap, header, outer


def _fit_into_box(image: Image.Image, box_size: tuple[int, int], background: tuple[int, int, int] = (255, 255, 255)) -> Image.Image:
    box_w, box_h = max(1, int(box_size[0])), max(1, int(box_size[1]))
    source = ImageOps.exif_transpose(image).convert("RGB")
    width, height = source.size
    if width <= 0 or height <= 0:
        return Image.new("RGB", (box_w, box_h), background)
    scale = min(box_w / width, box_h / height)
    next_size = (max(1, int(round(width * scale))), max(1, int(round(height * scale))))
    resized = source.resize(next_size, Image.LANCZOS)
    canvas = Image.new("RGB", (box_w, box_h), background)
    x = (box_w - resized.width) // 2
    y = (box_h - resized.height) // 2
    canvas.paste(resized, (x, y))
    return canvas


def _draw_compare_title(draw: ImageDraw.ImageDraw, xy: tuple[int, int], text: str, max_width: int, font) -> None:
    label = _fit_text(draw, text, font, max_width)
    draw.text(xy, label, fill=(41, 50, 64), font=font)


def _draw_compare_chip(draw: ImageDraw.ImageDraw, xy: tuple[int, int], text: str, font) -> None:
    x, y = xy
    label = _fit_text(draw, text, font, 220)
    bbox = draw.textbbox((0, 0), label, font=font)
    width = bbox[2] - bbox[0] + 22
    height = bbox[3] - bbox[1] + 14
    draw.rounded_rectangle((x, y, x + width, y + height), radius=max(8, height // 2), fill=(255, 255, 255), outline=(213, 220, 230), width=1)
    draw.text((x + 11, y + 6), label, fill=(47, 57, 72), font=font)


def make_saved_compare(
    image_paths: list[str],
    *,
    result_image: Image.Image,
    labels: list[str] | None = None,
    result_label: str = "结果",
) -> Image.Image:
    result = ImageOps.exif_transpose(result_image).convert("RGB")
    result_w, result_h = result.size
    gap, header, outer = _compare_unit(result.size)
    labels = labels or []

    references: list[tuple[str, Image.Image]] = []
    for index, path in enumerate(image_paths[:COMPARE_MAX_REFS], start=1):
        label = labels[index - 1] if index - 1 < len(labels) and labels[index - 1] else f"图{index}"
        try:
            references.append((label, _load_pil(path)))
        except Exception:
            references.append((label, blank_preview("加载失败", (max(320, result_w // 2), max(320, result_h // 2)))))

    has_refs = bool(references)
    left_w = result_w if has_refs else 0
    result_x = outer + (left_w + gap if has_refs else 0)
    image_y = outer + header
    canvas_w = outer * 2 + result_w + (left_w + gap if has_refs else 0)
    canvas_h = outer * 2 + header + result_h
    canvas = Image.new("RGB", (canvas_w, canvas_h), (244, 247, 250))
    draw = ImageDraw.Draw(canvas)

    title_font = _font(max(20, min(44, header // 2)), True)
    chip_font = _font(max(14, min(26, header // 3)), True)

    if has_refs:
        ref_title = "原图" if len(references) == 1 else "参考图"
        _draw_compare_title(draw, (outer, outer + max(4, header // 5)), ref_title, left_w, title_font)

        if len(references) == 1:
            cells = [(outer, image_y, left_w, result_h)]
        elif len(references) == 2:
            cell_h = max(1, (result_h - gap) // 2)
            cells = [
                (outer, image_y, left_w, cell_h),
                (outer, image_y + cell_h + gap, left_w, result_h - cell_h - gap),
            ]
        else:
            cols = 2
            rows = 2
            cell_w = max(1, (left_w - gap) // cols)
            cell_h = max(1, (result_h - gap) // rows)
            cells = []
            for idx in range(len(references)):
                col = idx % cols
                row = idx // cols
                x = outer + col * (cell_w + gap)
                y = image_y + row * (cell_h + gap)
                width = cell_w if col == 0 else left_w - cell_w - gap
                height = cell_h if row == 0 else result_h - cell_h - gap
                cells.append((x, y, max(1, width), max(1, height)))

        for (label, image), (x, y, width, height) in zip(references, cells):
            fitted = _fit_into_box(image, (width, height))
            canvas.paste(fitted, (x, y))
            draw.rectangle((x, y, x + width - 1, y + height - 1), outline=(216, 223, 232), width=2)
            _draw_compare_chip(draw, (x + max(10, gap // 3), y + max(10, gap // 3)), label, chip_font)

    _draw_compare_title(draw, (result_x, outer + max(4, header // 5)), result_label, result_w, title_font)
    canvas.paste(result, (result_x, image_y))
    draw.rectangle((result_x, image_y, result_x + result_w - 1, image_y + result_h - 1), outline=(74, 144, 226), width=max(2, min(6, gap // 8)))
    return canvas


def compare_output_path(output_root: str, output_rel_path: str) -> str:
    rel = clean_str(output_rel_path).replace("\\", "/").strip("/")
    if not rel:
        rel = "compare.png"
    folder = os.path.dirname(rel)
    stem = os.path.splitext(os.path.basename(rel))[0]
    name = f"{stem}_compare.png"
    parts = ["compare"]
    if folder:
        parts.extend(part for part in folder.split("/") if part)
    parts.append(name)
    path = os.path.abspath(os.path.normpath(os.path.join(output_root, *parts)))
    try:
        common = os.path.commonpath([output_root, path])
    except ValueError:
        common = ""
    if os.path.normcase(common) != os.path.normcase(output_root):
        raise ValueError("对比图路径非法，不能跳出输出文件夹。")
    return path


def compare_assets_dir(output_root: str, output_rel_path: str) -> str:
    rel = clean_str(output_rel_path).replace("\\", "/").strip("/")
    folder = os.path.dirname(rel)
    stem = os.path.splitext(os.path.basename(rel))[0] if rel else "item"
    stem = _safe_component(stem or "item")
    parts = ["compare_assets"]
    if folder:
        parts.extend(_safe_component(part) for part in folder.split("/") if part)
    parts.append(stem)
    path = os.path.abspath(os.path.normpath(os.path.join(output_root, *parts)))
    try:
        common = os.path.commonpath([output_root, path])
    except ValueError:
        common = ""
    if os.path.normcase(common) != os.path.normcase(output_root):
        raise ValueError("对比素材路径非法，不能跳出输出文件夹。")
    return path
