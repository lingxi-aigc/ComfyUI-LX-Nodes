"""
图像格式转换工具

tensor <-> PIL Image 双向转换，供 lb_image.py 节点调用。
"""

from typing import List
import numpy as np
import torch
from PIL import Image


def pil2tensor(img: Image.Image) -> torch.Tensor:
    """将 PIL Image 转换为 ComfyUI IMAGE Tensor: (B, H, W, C), float32, [0,1]。"""
    if img.mode != "RGB":
        img = img.convert("RGB")
    arr = np.asarray(img).astype(np.float32) / 255.0
    return torch.from_numpy(arr).unsqueeze(0)


def _tensor_image_to_array(tensor: torch.Tensor, layout: str = "auto") -> np.ndarray:
    t = tensor.detach().cpu()
    if t.ndim != 3:
        raise ValueError(f"Unsupported image tensor shape: {tuple(t.shape)}")

    if layout == "hwc":
        arr = t.numpy()
    elif layout == "chw":
        arr = t.permute(1, 2, 0).numpy()
    elif t.shape[-1] in (1, 3, 4):
        arr = t.numpy()
    elif t.shape[0] in (1, 3, 4):
        arr = t.permute(1, 2, 0).numpy()
    else:
        raise ValueError(f"Unsupported image tensor shape: {tuple(t.shape)}")

    if arr.shape[-1] == 1:
        arr = np.repeat(arr, 3, axis=-1)
    elif arr.shape[-1] == 4:
        arr = arr[..., :3]

    if arr.size and float(np.nanmax(arr)) > 1.0 + 1e-3:
        arr = arr / 255.0
    arr = np.nan_to_num(arr, nan=0.0, posinf=1.0, neginf=0.0)
    return (np.clip(arr, 0.0, 1.0) * 255.0).astype(np.uint8)


def tensor2pil(tensor: torch.Tensor) -> List[Image.Image]:
    """将 PyTorch Tensor 转换为 PIL Image 列表。

    输入格式：
        ComfyUI native: (B, H, W, C) 或 (H, W, C)
        legacy:        (B, C, H, W) 或 (C, H, W)
    """
    if tensor.dim() == 3:
        layout = "hwc" if tensor.shape[-1] in (1, 3, 4) else "chw"
        tensor = tensor.unsqueeze(0)
    elif tensor.dim() == 4:
        if tensor.shape[-1] in (1, 3, 4):
            layout = "hwc"
        elif tensor.shape[1] in (1, 3, 4):
            layout = "chw"
        else:
            layout = "auto"
    else:
        raise ValueError(f"Unsupported image tensor shape: {tuple(tensor.shape)}")

    result: List[Image.Image] = []
    for i in range(tensor.shape[0]):
        arr = _tensor_image_to_array(tensor[i], layout)
        result.append(Image.fromarray(arr, mode="RGB"))
    return result
