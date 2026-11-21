from __future__ import annotations

import os
import uuid
from typing import Any

import folder_paths
import numpy as np
import torch
from PIL import Image

from ..categories import LX_UTILITY_CATEGORY


class AnyType(str):
    def __ne__(self, value: object) -> bool:
        return False


ANY = AnyType("*")
MAX_PREVIEWS = 8


def _shape(value: Any) -> list[int] | None:
    if hasattr(value, "shape"):
        try:
            return [int(item) for item in value.shape]
        except Exception:
            return None
    return None


def _normalize_image_array(arr: np.ndarray) -> np.ndarray:
    if arr.ndim == 2:
        arr = np.stack([arr, arr, arr], axis=-1)
    elif arr.ndim == 3 and arr.shape[-1] == 1:
        arr = np.repeat(arr, 3, axis=-1)
    elif arr.ndim == 3 and arr.shape[-1] > 3:
        arr = arr[..., :3]

    arr = np.nan_to_num(arr.astype(np.float32), nan=0.0, posinf=1.0, neginf=0.0)
    if arr.size and float(np.max(arr)) > 1.0 + 1e-3:
        arr = arr / 255.0
    return (np.clip(arr, 0.0, 1.0) * 255.0).astype(np.uint8)


def _tensor_to_image_batches(tensor: torch.Tensor) -> list[np.ndarray]:
    data = tensor.detach().cpu()
    if data.ndim == 3:
        data = data.unsqueeze(0)
    if data.ndim != 4:
        return []
    if data.shape[-1] not in (1, 3, 4):
        return []
    return [_normalize_image_array(item.numpy()) for item in data]


def _tensor_to_mask_batches(tensor: torch.Tensor) -> list[np.ndarray]:
    data = tensor.detach().cpu()
    if data.ndim == 2:
        data = data.unsqueeze(0)
    elif data.ndim == 4 and data.shape[1] == 1:
        data = data[:, 0, :, :]
    elif data.ndim == 4 and data.shape[-1] == 1:
        data = data[..., 0]
    if data.ndim != 3:
        return []

    masks = []
    for item in data:
        arr = item.numpy()
        arr = np.nan_to_num(arr.astype(np.float32), nan=0.0, posinf=1.0, neginf=0.0)
        if arr.size and float(np.max(arr)) > 1.0 + 1e-3:
            arr = arr / 255.0
        gray = (np.clip(arr, 0.0, 1.0) * 255.0).astype(np.uint8)
        masks.append(np.stack([gray, gray, gray], axis=-1))
    return masks


def _save_preview(arr: np.ndarray, label: str) -> dict[str, Any]:
    temp_root = folder_paths.get_temp_directory()
    subfolder = "lx_show_any"
    dest_dir = os.path.join(temp_root, subfolder)
    os.makedirs(dest_dir, exist_ok=True)

    filename = f"{label}_{uuid.uuid4().hex}.png"
    path = os.path.join(dest_dir, filename)
    Image.fromarray(arr).save(path, compress_level=1)
    height, width = arr.shape[:2]
    return {
        "filename": filename,
        "subfolder": subfolder,
        "type": "temp",
        "width": int(width),
        "height": int(height),
    }


def _stringify_value(value: Any) -> str:
    if isinstance(value, str):
        return value
    try:
        import json

        return json.dumps(value, ensure_ascii=False, indent=2)
    except Exception:
        return repr(value)


def _tensor_preview_payload(value: torch.Tensor) -> dict[str, Any]:
    shape = _shape(value) or []
    images: list[dict[str, Any]] = []

    is_image = len(shape) == 4 and shape[-1] in (1, 3, 4)
    is_mask = is_image is False and (
        len(shape) in (2, 3) or (len(shape) == 4 and (shape[1] == 1 or shape[-1] == 1))
    )

    if is_image:
        for index, arr in enumerate(_tensor_to_image_batches(value)[:MAX_PREVIEWS], start=1):
            images.append(_save_preview(arr, f"image_{index}"))
    elif is_mask:
        for index, arr in enumerate(_tensor_to_mask_batches(value)[:MAX_PREVIEWS], start=1):
            images.append(_save_preview(arr, f"mask_{index}"))

    return {"images": images}


def _build_payload(value: Any) -> dict[str, Any]:
    if torch.is_tensor(value):
        payload = _tensor_preview_payload(value)
        if payload["images"]:
            return payload

    if isinstance(value, dict) and torch.is_tensor(value.get("samples")):
        return {"text": [_stringify_value(value)]}

    return {"text": [_stringify_value(value)]}


class LXShowAny:
    """Display any incoming value and pass it through unchanged."""

    CATEGORY = LX_UTILITY_CATEGORY
    SEARCH_ALIASES = ["lx", "LX", "灵犀", "展示任意", "显示任意", "show any"]
    RETURN_TYPES = (ANY,)
    RETURN_NAMES = ("输出",)
    FUNCTION = "show"
    OUTPUT_NODE = True

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "输入": (ANY, {"forceInput": True}),
            },
        }

    def show(self, 输入: Any = None):
        ui = _build_payload(输入)
        return {
            "ui": ui,
            "result": (输入,),
        }
