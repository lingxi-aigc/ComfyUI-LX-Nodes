# -*- coding: utf-8 -*-
"""
图片压缩节点实现
"""

import io
import os
import time
import numpy as np
from PIL import Image
import torch
import comfy.utils

from ..categories import LX_IMAGE_CATEGORY

MAX_DYNAMIC_RESIZE_ROUTES = 32
DEFAULT_RESIZE_ROUTES = 4

try:
    from nodes import MAX_RESOLUTION
except ImportError:
    MAX_RESOLUTION = 16384

try:
    import folder_paths
except ImportError:
    folder_paths = None


def get_output_directory():
    """
    获取 ComfyUI 输出目录，缺失时回退到相对 output 目录。
    """
    if folder_paths is not None and hasattr(folder_paths, "get_output_directory"):
        return folder_paths.get_output_directory()
    return "output"


def get_temp_directory():
    """
    获取 ComfyUI 临时目录，缺失时回退到 output 目录。
    """
    if folder_paths is not None and hasattr(folder_paths, "get_temp_directory"):
        return folder_paths.get_temp_directory()
    return get_output_directory()


def unwrap_quoted_path(path_value):
    """
    去掉路径首尾空白和成对包裹引号。
    """
    unwrapped = (path_value or "").strip()
    if len(unwrapped) >= 2 and unwrapped[0] == unwrapped[-1] and unwrapped[0] in {"'", '"'}:
        unwrapped = unwrapped[1:-1].strip()
    return unwrapped


def normalize_directory_path(directory_path):
    """
    规范化目录路径，兼容包裹引号、环境变量和用户目录。
    """
    normalized = unwrap_quoted_path(directory_path)
    normalized = os.path.expandvars(os.path.expanduser(normalized))
    return os.path.abspath(os.path.normpath(normalized))


def tensor_image_to_uint8_numpy(image_tensor):
    """
    将 ComfyUI 图像张量安全转换为 uint8 numpy 数组。
    """
    img_np = image_tensor.cpu().numpy()
    img_np = np.clip(np.rint(img_np * 255.0), 0, 255).astype(np.uint8)
    return img_np


def sanitize_filename_prefix(filename_prefix):
    """
    清理文件名前缀，避免路径穿越和非法目录写入。
    """
    if not filename_prefix:
        return "Comfyui_"

    invalid_chars = '<>:"/\\|?*'
    sanitized = "".join("_" if ch in invalid_chars or ord(ch) < 32 else ch for ch in filename_prefix)
    sanitized = sanitized.strip().rstrip(".")
    sanitized = sanitized[:120]
    return sanitized or "Comfyui_"


def build_unique_output_path(directory, filename_prefix, timestamp, index, extension):
    """
    生成不会覆盖已有文件的输出路径。
    """
    base_filename = f"{filename_prefix}{timestamp}_{index}{extension}"
    file_path = os.path.join(directory, base_filename)
    duplicate_index = 1

    while os.path.exists(file_path):
        base_filename = f"{filename_prefix}{timestamp}_{index}_{duplicate_index}{extension}"
        file_path = os.path.join(directory, base_filename)
        duplicate_index += 1

    return base_filename, file_path


def prepare_image_for_jpeg_pipeline(img_np):
    """
    规范化图像通道，生成可进入 JPEG 流程的 RGB 图像，并按需保留 alpha。
    """
    if img_np.ndim == 2:
        rgb_np = np.stack([img_np] * 3, axis=-1)
        return Image.fromarray(rgb_np, mode="RGB"), None

    channel_count = img_np.shape[-1]

    if channel_count == 1:
        rgb_np = np.repeat(img_np, 3, axis=-1)
        return Image.fromarray(rgb_np, mode="RGB"), None

    if channel_count == 2:
        gray_channel = img_np[..., :1]
        alpha_channel = img_np[..., 1:2]
        rgb_np = np.repeat(gray_channel, 3, axis=-1)
        return Image.fromarray(rgb_np, mode="RGB"), alpha_channel

    if channel_count >= 4:
        alpha_channel = img_np[..., 3:4]
        return Image.fromarray(img_np[..., :3], mode="RGB"), alpha_channel

    return Image.fromarray(img_np[..., :3], mode="RGB"), None


def prepare_image_for_save(img_np):
    """
    生成保存用的 RGB/JPG 图像。
    """
    if img_np.ndim == 2:
        img_rgb = np.stack([img_np] * 3, axis=-1)
        return Image.fromarray(img_rgb, mode="RGB"), ".jpg", "JPEG", {"quality": 90, "optimize": True}, False

    channel_count = img_np.shape[-1]

    if channel_count == 1:
        img_rgb = np.repeat(img_np, 3, axis=-1)
        return Image.fromarray(img_rgb, mode="RGB"), ".jpg", "JPEG", {"quality": 90, "optimize": True}, False

    if channel_count == 2:
        gray_channel = img_np[..., :1]
        img_rgb = np.repeat(gray_channel, 3, axis=-1)
        return Image.fromarray(img_rgb, mode="RGB"), ".jpg", "JPEG", {"quality": 90, "optimize": True}, False

    if channel_count == 3:
        return Image.fromarray(img_np, mode="RGB"), ".jpg", "JPEG", {"quality": 90, "optimize": True}, False

    if channel_count >= 4:
        rgb = img_np[..., :3]
        return Image.fromarray(rgb, mode="RGB"), ".jpg", "JPEG", {"quality": 90, "optimize": True}, False

    return Image.fromarray(img_np[..., :3], mode="RGB"), ".jpg", "JPEG", {"quality": 90, "optimize": True}, False


def align_dimension_to_factor(value, factor, use_ceil):
    """
    将尺寸修正为因数的整数倍；factor 为 0 时不修正。
    """
    value = max(1, int(round(value)))
    factor = max(0, int(factor))
    if factor == 0:
        return value

    if use_ceil:
        aligned = ((value + factor - 1) // factor) * factor
    else:
        aligned = (value // factor) * factor
        if aligned == 0:
            aligned = factor

    return max(1, aligned)


def clamp_resize_route_count(value):
    try:
        count = int(value)
    except (TypeError, ValueError):
        count = DEFAULT_RESIZE_ROUTES
    return max(1, min(MAX_DYNAMIC_RESIZE_ROUTES, count))


def resize_tensor_image_by_side(image, size, factor, mode):
    source_height = int(image.shape[1])
    source_width = int(image.shape[2])

    if source_width <= 0 or source_height <= 0:
        return image, source_width, source_height

    target_side = max(1, int(size))
    use_min_side = not bool(mode)
    current_side = min(source_width, source_height) if use_min_side else max(source_width, source_height)
    scale = target_side / current_side

    scaled_width = source_width * scale
    scaled_height = source_height * scale
    output_width = align_dimension_to_factor(scaled_width, factor, use_min_side)
    output_height = align_dimension_to_factor(scaled_height, factor, use_min_side)

    if output_width == source_width and output_height == source_height:
        return image, output_width, output_height

    samples = image.movedim(-1, 1)
    resized = comfy.utils.common_upscale(
        samples,
        output_width,
        output_height,
        "lanczos",
        "disabled",
    ).movedim(1, -1)

    return resized, output_width, output_height


class LXImageResizeBySide:
    """
    按最长边或最短边等比缩放图像，并自动对齐到指定因数。
    """
    DESCRIPTION = "按最长边或最短边等比缩放 IMAGE，并将输出宽高自动对齐到指定因数。"
    SEARCH_ALIASES = [
        "lx",
        "LX",
        "灵犀",
        "图像缩放",
        "图像缩放按边",
        "按边缩放",
        "image resize",
        "resize by side",
        "scale by side",
    ]

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "图像": ("IMAGE",),
                "尺寸": ("INT", {
                    "default": 1024,
                    "min": 1,
                    "max": MAX_RESOLUTION,
                    "step": 1,
                    "display": "number",
                }),
                "因数": ("INT", {
                    "default": 8,
                    "min": 0,
                    "max": 512,
                    "step": 1,
                    "display": "number",
                }),
                "模式": ("BOOLEAN", {
                    "default": False,
                    "label_on": "max",
                    "label_off": "mini",
                    "tooltip": "max：按最长边缩放；mini：按最短边缩放。",
                }),
            },
        }

    RETURN_TYPES = ("IMAGE", "INT", "INT")
    RETURN_NAMES = ("图像", "宽度", "高度")
    FUNCTION = "resize_by_side"
    CATEGORY = LX_IMAGE_CATEGORY

    def resize_by_side(self, 图像, 尺寸, 因数, 模式):
        resized, output_width, output_height = resize_tensor_image_by_side(图像, 尺寸, 因数, 模式)
        return (resized, output_width, output_height)


class LXImageMultiResizeBySide:
    """
    多路 IMAGE 共用同一组参数做按边缩放，每一路输入对应同序号输出。
    """
    DESCRIPTION = "多路 IMAGE 共用尺寸、因数和模式做按边缩放，适合多图分支工作流。"
    SEARCH_ALIASES = [
        "lx",
        "LX",
        "灵犀",
        "图像多路缩放",
        "多路图像缩放",
        "图像缩放按边",
        "multi image resize",
        "multi resize by side",
    ]

    @classmethod
    def INPUT_TYPES(cls):
        optional_images = {
            f"图像{index}": ("IMAGE",)
            for index in range(1, MAX_DYNAMIC_RESIZE_ROUTES + 1)
        }
        return {
            "required": {
                "尺寸": ("INT", {
                    "default": 1024,
                    "min": 1,
                    "max": MAX_RESOLUTION,
                    "step": 1,
                    "display": "number",
                }),
                "因数": ("INT", {
                    "default": 8,
                    "min": 0,
                    "max": 512,
                    "step": 1,
                    "display": "number",
                }),
                "模式": ("BOOLEAN", {
                    "default": False,
                    "label_on": "max",
                    "label_off": "mini",
                    "tooltip": "max：按最长边缩放；mini：按最短边缩放。",
                }),
                "数量": ("INT", {
                    "default": DEFAULT_RESIZE_ROUTES,
                    "min": 1,
                    "max": MAX_DYNAMIC_RESIZE_ROUTES,
                    "step": 1,
                    "display": "number",
                }),
            },
            "optional": optional_images,
        }

    RETURN_TYPES = ("IMAGE",) * MAX_DYNAMIC_RESIZE_ROUTES
    RETURN_NAMES = tuple(f"图像{index}" for index in range(1, MAX_DYNAMIC_RESIZE_ROUTES + 1))
    FUNCTION = "resize_multi_by_side"
    CATEGORY = LX_IMAGE_CATEGORY

    def resize_multi_by_side(self, 尺寸, 因数, 模式, 数量=DEFAULT_RESIZE_ROUTES, **kwargs):
        route_count = clamp_resize_route_count(数量)
        outputs = []
        missing_routes = []

        for index in range(1, route_count + 1):
            image = kwargs.get(f"图像{index}")
            if image is None:
                missing_routes.append(index)
                continue
            resized, _, _ = resize_tensor_image_by_side(image, 尺寸, 因数, 模式)
            outputs.append(resized)

        if missing_routes:
            names = "、".join(f"图像{index}" for index in missing_routes)
            raise ValueError(f"图像批量缩放（按边）当前数量为 {route_count}，但缺少输入：{names}。请连接对应图像，或降低“数量”；接口会随数量自动更新。")

        return tuple(outputs)


class ImageCompression:
    """
    高质量图片压缩节点
    """
    DESCRIPTION = "按 JPEG 质量在内存中压缩图片，适合减小体积后继续接后续节点。"
    SEARCH_ALIASES = [
        "lx",
        "LX",
        "灵犀",
        "LX_图像高质压缩",
        "LX图像高质压缩",
        "LX_图片压缩",
        "LX图片压缩",
        "图像高质压缩",
        "图片压缩",
        "JPEG压缩",
        "JPG压缩",
        "ImageCompression",
    ]

    @classmethod
    def INPUT_TYPES(s):
        """
        定义节点的输入类型
        """
        return {
            "required": {
                "图像": ("IMAGE",),
                "压缩质量": ("INT", {
                    "default": 90,
                    "min": 0,
                    "max": 100,
                    "step": 1,
                    "display": "number",
                    "tooltip": "0-100；数值越低体积越小，80-95 通常比较稳。"
                }),
            },
        }
    
    RETURN_TYPES = ("IMAGE",)
    RETURN_NAMES = ("图像",)
    FUNCTION = "compress"
    CATEGORY = LX_IMAGE_CATEGORY
    
    def compress(self, 图像, 压缩质量):
        """
        执行图像压缩
        """
        # 转换ComfyUI图像格式到PIL图像
        # ComfyUI的图像格式是：[batch, height, width, channels]，值范围是[0, 1]
        
        # 获取原始图像数据
        batch_size = 图像.shape[0]
        compressed_images = []
        
        for i in range(batch_size):
            # 获取单张图像
            img = 图像[i]
            
            # 转换为[0, 255]范围的numpy数组
            img_np = tensor_image_to_uint8_numpy(img)
            pil_img, _ = prepare_image_for_jpeg_pipeline(img_np)
            
            # 执行JPG压缩（使用内存中的BytesIO，避免磁盘IO）
            buffer_compressed = io.BytesIO()
            pil_img.save(buffer_compressed, format="JPEG", quality=压缩质量, optimize=True, subsampling=1)
            
            # 转换回PIL图像
            buffer_compressed.seek(0)
            pil_img_compressed = Image.open(buffer_compressed)
            
            # 转换回numpy数组
            img_compressed_np = np.array(pil_img_compressed)
            
            # 确保通道数正确（如果是灰度图，转换为RGB）
            if len(img_compressed_np.shape) == 2:  # 灰度图
                img_compressed_np = np.stack([img_compressed_np] * 3, axis=-1)
            elif img_compressed_np.shape[-1] == 1:  # 单通道图
                img_compressed_np = np.repeat(img_compressed_np, 3, axis=-1)

            # 转换回ComfyUI图像格式
            img_compressed_np = img_compressed_np.astype(np.float32) / 255.0
            img_compressed_tensor = torch.from_numpy(img_compressed_np)
            compressed_images.append(img_compressed_tensor)
        
        # 堆叠压缩后的图像
        compressed_images_tensor = torch.stack(compressed_images)
        
        return (compressed_images_tensor,)

class SaveJPGImage:
    """
    保存JPG图像节点
    """
    DESCRIPTION = "把 IMAGE 保存为 JPG，可指定文件名前缀和保存路径。"
    SEARCH_ALIASES = [
        "lx",
        "LX",
        "灵犀",
        "LX_保存图像（JPG）",
        "LX保存JPG",
        "LX保存JPEG",
        "LX_保存JPG",
        "LX_保存JPEG",
        "保存图像（JPG）",
        "保存JPG",
        "保存JPEG",
        "SaveJPGImage",
    ]

    @classmethod
    def INPUT_TYPES(s):
        """
        定义节点的输入类型
        """
        return {
            "required": {
                "图像": ("IMAGE",),
                "文件名前缀": ("STRING", {
                    "default": "Comfyui_",
                    "tooltip": "保存文件名前缀，会自动追加时间戳和序号。",
                }),
            },
            "hidden": {
                "prompt": "PROMPT",
                "extra_pnginfo": "EXTRA_PNGINFO",
            },
            "optional": {
                "保存路径": ("STRING", {
                    "default": "",
                    "tooltip": "留空保存到 ComfyUI 默认 output；填写后保存到指定目录。",
                }),
            },
        }
    
    RETURN_TYPES = ()
    RETURN_NAMES = ()
    FUNCTION = "save_jpg"
    CATEGORY = LX_IMAGE_CATEGORY
    OUTPUT_NODE = True
    
    def save_jpg(self, 图像, 文件名前缀, 保存路径="", prompt=None, extra_pnginfo=None):
        """
        保存图像为JPG格式（默认质量90）
        """
        from datetime import datetime
        
        # 仅在未指定自定义路径时使用默认 output 目录。
        # 指定 save_path 后，以 save_path 为唯一正式保存位置；节点预览写入 temp。
        preview_dir = normalize_directory_path(get_output_directory())
        temp_preview_dir = normalize_directory_path(get_temp_directory())
        custom_save_path = unwrap_quoted_path(保存路径)
        actual_dir = normalize_directory_path(custom_save_path) if custom_save_path else preview_dir
        safe_filename_prefix = sanitize_filename_prefix(文件名前缀)
        
        # 确保实际保存目录存在
        if not os.path.exists(actual_dir):
            os.makedirs(actual_dir, exist_ok=True)
        if custom_save_path and not os.path.exists(temp_preview_dir):
            os.makedirs(temp_preview_dir, exist_ok=True)
        
        batch_size = 图像.shape[0]
        saved_images = []
        saved_paths = []
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        
        # 处理每张图像
        for i in range(batch_size):
            # 获取单张图像
            img = 图像[i]
            
            # 转换为[0, 255]范围的numpy数组
            img_np = tensor_image_to_uint8_numpy(img)

            pil_img, _ = prepare_image_for_jpeg_pipeline(img_np)
            file_extension = ".jpg"
            file_format = "JPEG"
            save_kwargs = {"quality": 90, "optimize": True, "subsampling": 1}
            
            # 生成唯一文件名
            filename, actual_file_path = build_unique_output_path(
                actual_dir,
                safe_filename_prefix,
                timestamp,
                i + 1,
                file_extension,
            )

            # 保存到实际目录
            pil_img.save(actual_file_path, format=file_format, **save_kwargs)
            saved_paths.append(actual_file_path)
            
            if custom_save_path:
                preview_filename, preview_file_path = build_unique_output_path(
                    temp_preview_dir,
                    f"{safe_filename_prefix}preview_",
                    timestamp,
                    i + 1,
                    file_extension,
                )
                pil_img.save(preview_file_path, format=file_format, **save_kwargs)
                saved_images.append({
                    "filename": preview_filename,
                    "subfolder": "",
                    "type": "temp"
                })
            else:
                subfolder = os.path.relpath(actual_dir, preview_dir)
                if subfolder == ".":
                    subfolder = ""

                saved_images.append({
                    "filename": filename,
                    "subfolder": subfolder,
                    "type": "output"
                })
        
        if custom_save_path:
            return {
                "ui": {
                    "images": saved_images,
                    "text": saved_paths
                },
                "result": ()
            }

        return {
            "ui": {
                "images": saved_images
            },
            "result": ()
        }

    @classmethod
    def IS_CHANGED(s, 图像, 文件名前缀, 保存路径="", prompt=None, extra_pnginfo=None):
        """
        让保存节点每次都重新执行，避免同输入时被 ComfyUI 缓存跳过。
        """
        return time.time()
