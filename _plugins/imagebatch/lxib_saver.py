# LX_保存图像（文件夹）：按输入子目录结构写入保存路径
# 新增：文件名前缀、文件名后缀、保存格式（PNG/JPG/WEBP）、图像质量
# 目录模板: CATEGORY = "🅻🆇 灵犀/文件夹批量"

import glob
import hashlib
import os
from typing import List, Optional

import numpy as np
import torch
import folder_paths
from PIL import Image

from ..categories import LX_FOLDER_CATEGORY

# 旧版占位文件名（仅用于清理历史残留）
_LEGACY_EMPTY_MARKER = ".__学源_空文件夹__.txt"

from .lxib_folder_shared import pop_pending_empty_folders

# 支持显式指定保存格式
_SAVE_FORMATS = ["保持原格式", "PNG", "JPG", "WEBP"]
_FORMAT_TO_EXT = {
    "PNG": ".png",
    "JPG": ".jpg",
    "WEBP": ".webp",
}


def _tensor_to_pil(image: torch.Tensor) -> Image.Image:
    """
    ComfyUI IMAGE 张量约定为 (B, H, W, C)，float32，值域 [0,1]（0~255 也会被兼容）。
    返回单张 PIL.Image（取 batch 维第 0 张；带 alpha 时只保留 RGB）。
    """
    arr = image.detach().cpu().numpy()
    if arr.ndim == 4:
        arr = arr[0]
    if arr.ndim == 2:
        arr = np.stack([arr, arr, arr], axis=-1)
    elif arr.ndim == 3 and arr.shape[-1] > 3:
        arr = arr[..., :3]
    has_large = arr.size and float(np.max(arr)) > 1.0 + 1e-3
    if has_large:
        arr = arr / 255.0
    if np.any(np.isnan(arr)):
        arr = np.nan_to_num(arr, nan=0.0, posinf=1.0, neginf=0.0)
    arr = np.clip(arr, 0.0, 1.0)
    rgb = (arr * 255.0).astype(np.uint8)
    return Image.fromarray(rgb).convert("RGB")


def _save_pil_with_format(
    pil: Image.Image,
    dest_path: str,
    save_format: str,
    quality: int,
) -> None:
    """
    按 save_format 保存 PIL Image 到 dest_path。
    dest_path 的扩展名已由调用方按格式替换，本函数只管按 format 编码写入。
    """
    fmt = (save_format or "保持原格式").strip()

    if fmt == "PNG":
        pil.save(dest_path, format="PNG")
    elif fmt in ("JPG", "JPEG"):
        pil_rgb = pil.convert("RGB") if pil.mode != "RGB" else pil
        pil_rgb.save(dest_path, format="JPEG", quality=int(quality))
    elif fmt == "WEBP":
        pil_rgb = pil.convert("RGB") if pil.mode != "RGB" else pil
        pil_rgb.save(dest_path, format="WEBP", quality=int(quality))
    else:
        # 保持原格式：看 dest_path 现有后缀
        ext = os.path.splitext(dest_path)[1].lower()
        if ext in (".jpg", ".jpeg"):
            pil_rgb = pil.convert("RGB") if pil.mode != "RGB" else pil
            pil_rgb.save(dest_path, format="JPEG", quality=int(quality))
        elif ext == ".webp":
            pil_rgb = pil.convert("RGB") if pil.mode != "RGB" else pil
            pil_rgb.save(dest_path, format="WEBP", quality=int(quality))
        elif ext == ".bmp":
            pil.save(dest_path, format="BMP")
        elif ext in (".tiff", ".tif"):
            pil.save(dest_path, format="TIFF")
        elif ext == ".png" or not ext:
            pil.save(dest_path, format="PNG")
        else:
            pil.save(dest_path)


def _is_empty_folder_item(filename: str) -> bool:
    name = str(filename or "").strip()
    return not name or name == _LEGACY_EMPTY_MARKER


def _unwrap_quoted_path(path_value: str) -> str:
    value = str(path_value or "").strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        value = value[1:-1].strip()
    return value


def _sanitize_filename_affix(value: str) -> str:
    """Sanitize filename prefix/suffix fragments without changing normal text."""
    text = str(value or "").strip()
    if not text:
        return ""
    invalid = '<>:"/\\|?*'
    clean = "".join("_" if ch in invalid or ord(ch) < 32 else ch for ch in text)
    return clean.rstrip(" .")


def _normalize_directory_path(directory_path: str) -> str:
    normalized = _unwrap_quoted_path(directory_path)
    normalized = os.path.expandvars(os.path.expanduser(normalized))
    return os.path.abspath(os.path.normpath(normalized))


def _safe_preview_stem(filename: str) -> str:
    stem = os.path.splitext(os.path.basename(str(filename or "")))[0] or "image"
    invalid = '<>:"/\\|?*'
    clean = "".join("_" if ch in invalid or ord(ch) < 32 else ch for ch in stem)
    clean = clean.strip().rstrip(".") or "image"
    return clean[:80]


def _output_image_result(file_path: str, output_root: str) -> Optional[dict]:
    abs_file = os.path.abspath(os.path.normpath(file_path))
    output_root = os.path.abspath(os.path.normpath(output_root))
    file_dir = os.path.dirname(abs_file)
    try:
        common = os.path.commonpath([output_root, file_dir])
    except ValueError:
        return None
    if os.path.normcase(common) != os.path.normcase(output_root):
        return None

    subfolder = os.path.relpath(file_dir, output_root)
    if subfolder == ".":
        subfolder = ""
    return {
        "filename": os.path.basename(abs_file),
        "subfolder": subfolder.replace("\\", "/"),
        "type": "output",
    }


def _temp_preview_result(file_path: str) -> Optional[dict]:
    abs_file = os.path.abspath(os.path.normpath(file_path))
    try:
        source_mtime = os.path.getmtime(abs_file)
        source_stat = os.stat(abs_file)
        digest_source = f"{abs_file}|{getattr(source_stat, 'st_mtime_ns', int(source_mtime * 1_000_000_000))}"
        digest = hashlib.sha1(digest_source.encode("utf-8", errors="ignore")).hexdigest()[:12]
        preview_name = f"lx_save_preview_{_safe_preview_stem(abs_file)}_{digest}.png"
        temp_root = _normalize_directory_path(folder_paths.get_temp_directory())
        os.makedirs(temp_root, exist_ok=True)
        preview_path = os.path.join(temp_root, preview_name)

        if not os.path.isfile(preview_path) or os.path.getmtime(preview_path) < source_mtime:
            with Image.open(abs_file) as img:
                img.convert("RGB").save(preview_path, format="PNG", compress_level=1)

        return {
            "filename": preview_name,
            "subfolder": "",
            "type": "temp",
        }
    except Exception as exc:
        print(f"[LX保存图像] 创建预览失败: {exc}")
        return None


def _final_stem(stem: str, suffix: str) -> str:
    """把文件名后缀追加到 stem 之前（扩展名之前）。"""
    clean = _sanitize_filename_affix(suffix)
    return f"{stem}{clean}" if clean else stem


def _final_ext(stem: str, original_ext: str, save_format: str) -> str:
    """
    决定最终扩展名：
      - 显式格式 → 格式对应扩展名（覆盖原后缀）
      - 保持原格式 → 沿用 original_ext
    """
    fmt = (save_format or "保持原格式").strip()
    if fmt in _FORMAT_TO_EXT:
        return _FORMAT_TO_EXT[fmt]
    return original_ext


def _resolve_unique_filename(
    dest_dir: str,
    stem: str,
    original_ext: str,
    save_format: str,
    suffix: str,
) -> str:
    """
    防覆盖命名（同名追加后缀开启时调用）：
      1) 拼出「最终文件名」（前缀已在 stem 里），判断是否存在；
      2) 不存在 → 直接返回；
      3) 存在 → glob 一次找到所有冲突文件，二分查找最小空位返回（1 次 syscall）。
    """
    final_ext = _final_ext(stem, original_ext, save_format)
    final_stem = _final_stem(stem, suffix)
    base = f"{final_stem}{final_ext}"
    if not os.path.isfile(os.path.join(dest_dir, base)):
        return base

    escaped_stem = glob.escape(final_stem)
    pattern = os.path.join(glob.escape(dest_dir), f"{escaped_stem}-*{final_ext}")
    existing = set()
    for p in glob.glob(pattern):
        basename = os.path.basename(p)
        if basename.startswith(final_stem + "-"):
            num_part = basename[len(final_stem) + 1 : -len(final_ext)]
            try:
                existing.add(int(num_part))
            except ValueError:
                pass

    n = 1
    while n in existing:
        n += 1
    return f"{final_stem}-{n}{final_ext}"


class LXSaveFolderImage:
    """LX_保存图像（文件夹）：按输入子目录结构写入保存路径；支持文件名前缀 / 后缀 / 格式 / 质量。"""

    SEARCH_ALIASES = [
        "lx",
        "LX",
        "灵犀",
        "LX_保存图像（文件夹）",
        "LX保存图像",
        "LX_保存图像",
        "LX保存",
        "文件夹保存",
        "批量保存",
        "lx folder save",
        "lx save folder image",
        "LXSaveFolderImage",
    ]

    CATEGORY = LX_FOLDER_CATEGORY
    SIZE = (420, 360)
    RETURN_TYPES = ("IMAGE",)
    RETURN_NAMES = ("图像",)
    FUNCTION = "save_images"
    OUTPUT_NODE = True

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
                        "tooltip": "连接输入节点（子目录相对路径，无子目录时为空）",
                    },
                ),
                "图片名称": (
                    "STRING",
                    {
                        "default": "",
                        "forceInput": True,
                        "tooltip": "连接输入节点；空表示仅创建空文件夹",
                    },
                ),
                "保存路径": (
                    "STRING",
                    {
                        "default": "",
                        "multiline": False,
                        "placeholder": "留空 = ComfyUI 默认输出目录",
                        "tooltip": "图片保存的根目录；留空 → 使用 ComfyUI 默认输出目录，也可自定义保存路径。",
                    },
                ),
                "文件名前缀": (
                    "STRING",
                    {
                        "default": "",
                        "multiline": False,
                        "placeholder": "可空；拼在原名前，如 LX_",
                        "tooltip": "拼在原文件名前，例如填 LX_ → cat.jpg 变为 LX_cat.jpg；留空则使用原名。",
                    },
                ),
                "文件名后缀": (
                    "STRING",
                    {
                        "default": "",
                        "multiline": False,
                        "placeholder": "可空；拼在扩展名之前，如 _hd",
                        "tooltip": "拼在原文件名之后、扩展名之前，例如填 _hd → cat.jpg 变为 cat_hd.jpg；留空则不加后缀。",
                    },
                ),
                "保存格式": (
                    _SAVE_FORMATS,
                    {
                        "default": "保持原格式",
                        "tooltip": "始终决定实际保存的文件格式，与「文件名前缀」「文件名后缀」无关。保持原格式：沿用输入图片扩展名；PNG/JPG/WEBP：强制转为对应格式。",
                    },
                ),
                "图像质量": (
                    "INT",
                    {
                        "default": 95,
                        "min": 1,
                        "max": 100,
                        "step": 1,
                        "tooltip": "仅对 JPG / WEBP 生效；PNG 忽略",
                    },
                ),
                "同名追加后缀": (
                    "BOOLEAN",
                    {
                        "default": False,
                        "label_on": "追加",
                        "label_off": "覆盖",
                        "tooltip": "关闭（覆盖）：同名直接替换旧图——例如 1.jpg 已存在时再次保存会覆盖原文件。开启（追加）：仅当同名文件存在时才自动追加 -1、-2…避免覆盖，例如首次存 1.jpg、再次存 1-1.jpg、第三次存 1-2.jpg；无冲突时仍按原名保存。",
                    },
                ),
                "显示预览": (
                    "BOOLEAN",
                    {
                        "default": True,
                        "label_on": "显示",
                        "label_off": "关闭",
                        "tooltip": "控制节点下方是否显示保存后的图片预览；关闭后仍会正常保存并透传图像。",
                    },
                ),
            }
        }

    @staticmethod
    def _split_lines(value: str, count: int) -> List[str]:
        parts = [p.strip() for p in str(value).split("\n")]
        if len(parts) == 1 and count > 1:
            return parts * count
        if len(parts) < count:
            parts.extend([""] * (count - len(parts)))
        return parts[:count]

    @staticmethod
    def _apply_prefix(filename: str, prefix: str) -> str:
        clean_prefix = _sanitize_filename_affix(prefix)
        if not clean_prefix:
            return filename
        return f"{clean_prefix}{filename}"

    @staticmethod
    def _dest_dir(save_root: str, folder_path: str) -> str:
        save_root = os.path.abspath(os.path.normpath(save_root))
        folder_path = str(folder_path or "").strip().replace("\\", "/")
        if folder_path:
            # 先按路径分隔，再过滤非法部分，更可靠
            parts = [p for p in folder_path.split("/") if p and p != ".."]
            dest_dir = os.path.normpath(os.path.join(save_root, *parts))
        else:
            dest_dir = save_root
        try:
            common = os.path.commonpath([save_root, dest_dir])
        except ValueError:
            common = ""
        if os.path.normcase(common) != os.path.normcase(save_root):
            raise ValueError("文件夹名称非法，不能跳出保存根目录。")
        return dest_dir

    @staticmethod
    def _remove_legacy_marker(dest_dir: str) -> None:
        marker = os.path.join(dest_dir, _LEGACY_EMPTY_MARKER)
        if os.path.isfile(marker):
            try:
                os.remove(marker)
            except OSError:
                pass

    def _ensure_empty_dir(self, save_root: str, folder_path: str) -> None:
        dest_dir = self._dest_dir(save_root, folder_path)
        os.makedirs(dest_dir, exist_ok=True)
        self._remove_legacy_marker(dest_dir)

    def _save_image_file(
        self,
        save_root: str,
        folder_path: str,
        filename: str,
        image: torch.Tensor,
        prefix: str,
        suffix: str,
        append_suffix: bool,
        save_format: str,
        quality: int,
    ) -> tuple:
        """保存单张图片，返回 (filename, subfolder, full_path) 元组。"""
        dest_dir = self._dest_dir(save_root, folder_path)
        # 目录和 legacy marker 已在 batch 开头一次性处理

        # folder_path 即 subfolder（相对路径）
        subfolder = str(folder_path or "").strip().replace("\\", "/")

        filename = os.path.basename(str(filename or "").strip())
        if not filename or _is_empty_folder_item(filename):
            raise ValueError("图片名称无效。")

        # 1. 应用前缀
        filename = self._apply_prefix(filename, prefix)

        # 2. 分离 stem 和原扩展名
        stem, original_ext = os.path.splitext(filename)

        # 3. 应用文件名后缀到 stem
        final_stem = _final_stem(stem, suffix)

        # 4. 决定最终扩展名（格式优先）
        final_ext = _final_ext(final_stem, original_ext, save_format)

        # 5. 防覆盖命名（final_stem 已含后缀，不再重复应用）
        if append_suffix:
            save_name = _resolve_unique_filename(
                dest_dir, final_stem, original_ext, save_format, ""
            )
        else:
            save_name = f"{final_stem}{final_ext}"

        dest = os.path.abspath(os.path.normpath(os.path.join(dest_dir, save_name)))
        try:
            common = os.path.commonpath([dest_dir, os.path.dirname(dest)])
        except ValueError:
            common = ""
        if os.path.normcase(common) != os.path.normcase(dest_dir):
            raise ValueError("文件名非法，不能跳出保存目录。")

        # 6. 保存
        pil = _tensor_to_pil(image)
        _save_pil_with_format(pil, dest, save_format, quality)

        return save_name, subfolder, dest

    def save_images(
        self,
        图像: torch.Tensor,
        文件夹名称: str,
        图片名称: str,
        保存路径: str,
        文件名前缀: str = "",
        文件名后缀: str = "",
        保存格式: str = "保持原格式",
        图像质量: int = 95,
        同名追加后缀: bool = False,
        显示预览: bool = True,
        **legacy_kwargs,
    ):
        if "是否要后缀" in legacy_kwargs and "同名追加后缀" not in legacy_kwargs:
            同名追加后缀 = bool(legacy_kwargs.pop("是否要后缀"))
        legacy_kwargs.clear()

        if 图像 is None or len(图像) == 0:
            return {"ui": {"images": []}, "result": (torch.empty(0),)}

        output_root = _normalize_directory_path(folder_paths.get_output_directory())
        custom_save_root = _unwrap_quoted_path(保存路径)
        save_root = _normalize_directory_path(custom_save_root) if custom_save_root else output_root
        os.makedirs(save_root, exist_ok=True)

        # 批量创建空目录（去重，一次性创建所有必要目录）
        for folder_path in pop_pending_empty_folders():
            try:
                self._ensure_empty_dir(save_root, folder_path)
            except Exception as exc:
                print(f"[LX保存图像] 创建空文件夹失败: {exc}")

        batch = int(图像.shape[0])
        folders = self._split_lines(文件夹名称, batch)
        names = self._split_lines(图片名称, batch)

        success = 0
        failed = 0

        # 预计算所有目标目录并去重，减少 os.makedirs 调用
        needed_dirs: set = {save_root}
        for fp in folders:
            try:
                needed_dirs.add(self._dest_dir(save_root, fp))
            except Exception:
                pass
        for d in sorted(needed_dirs):
            os.makedirs(d, exist_ok=True)
            self._remove_legacy_marker(d)
        failed = 0
        results = []
        saved_paths = []
        used_temp_preview = False

        for i in range(batch):
            try:
                if _is_empty_folder_item(names[i]):
                    self._ensure_empty_dir(save_root, folders[i])
                else:
                    _save_name, _subfolder, saved_path = self._save_image_file(
                        save_root,
                        folders[i],
                        names[i],
                        图像[i],
                        文件名前缀,
                        文件名后缀,
                        同名追加后缀,
                        保存格式,
                        图像质量,
                    )
                    saved_paths.append(saved_path)
                    preview = _output_image_result(saved_path, output_root)
                    if preview is None:
                        preview = _temp_preview_result(saved_path)
                        used_temp_preview = used_temp_preview or preview is not None
                    if preview is not None:
                        results.append(preview)
                success += 1
            except Exception as exc:
                failed += 1
                print(f"[LX保存图像] 跳过第 {i + 1} 张: {exc}")

        if failed > 0:
            print(f"[LX保存图像] 完成：成功 {success} / 失败 {failed}")

        ui = {"images": results if 显示预览 else []}
        if used_temp_preview and saved_paths:
            ui["text"] = saved_paths
        return {"ui": ui, "result": (图像,)}


NODE_CLASS_MAPPINGS = {"LXSaveFolderImage": LXSaveFolderImage}
NODE_DISPLAY_NAME_MAPPINGS = {"LXSaveFolderImage": "保存图像（文件夹）"}
