# -*- coding: utf-8 -*-
from __future__ import annotations

import gc
import importlib.machinery
import importlib.util
import json
import os
import re
import sys
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any

import numpy as np
import torch
from PIL import Image, ImageFilter

import folder_paths

from ..categories import LX_IMAGE_CATEGORY

try:
    from transformers import AutoModelForImageSegmentation
except Exception:  # pragma: no cover - handled at runtime
    AutoModelForImageSegmentation = None


MODEL_ORDER = ["BEN2", "RMBG-2.0", "InSPyReNet", "BiRefNet-Matting", "BiRefNet-Dynamic"]

LX_MODEL_ROOT = os.path.join(folder_paths.models_dir, "LX", "auto_cutout")
LX_SEMANTIC_MODEL_ROOT = os.path.join(folder_paths.models_dir, "LX", "semantic_cutout")
LEGACY_RMBG_ROOT = os.path.join(folder_paths.models_dir, "RMBG")
LEGACY_REMBG_ROOT = os.path.join(folder_paths.models_dir, "rembg")
CUSTOM_NODES_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))

folder_paths.add_model_folder_path("lx_auto_cutout", LX_MODEL_ROOT)
folder_paths.add_model_folder_path("lx_semantic_cutout", LX_SEMANTIC_MODEL_ROOT)


def _normalize_resolution(value: int) -> int:
    value = max(256, min(2048, int(value)))
    return max(32, (value // 32) * 32)


def _unwrap_quotes(value: str | None) -> str:
    text = (value or "").strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in {"'", '"'}:
        text = text[1:-1].strip()
    return text


def _ensure_dir(path: str) -> None:
    os.makedirs(path, exist_ok=True)


def _clamp01(array: np.ndarray) -> np.ndarray:
    return np.clip(np.nan_to_num(array.astype(np.float32), nan=0.0, posinf=1.0, neginf=0.0), 0.0, 1.0)


def _tensor_to_pil_image(image_tensor: torch.Tensor) -> Image.Image:
    array = image_tensor.detach().cpu().numpy()
    array = _clamp01(array)

    if array.ndim == 2:
        array = np.stack([array, array, array], axis=-1)
    elif array.ndim == 3 and array.shape[-1] == 1:
        array = np.repeat(array, 3, axis=-1)
    elif array.ndim == 3 and array.shape[-1] not in (3, 4):
        array = array[..., :3]

    return Image.fromarray((array * 255.0).astype(np.uint8))


def _image_batch_to_pils(image_batch: torch.Tensor) -> list[Image.Image]:
    data = image_batch.detach().cpu()
    if data.ndim == 3:
        data = data.unsqueeze(0)
    if data.ndim != 4:
        raise ValueError("image batch must be a 4D tensor")
    return [_tensor_to_pil_image(data[index]) for index in range(data.shape[0])]


def _pil_to_mask_tensor(mask: Image.Image) -> torch.Tensor:
    gray = np.array(mask.convert("L"), dtype=np.float32) / 255.0
    return torch.from_numpy(gray)


def _pil_to_image_tensor(image: Image.Image) -> torch.Tensor:
    if image.mode == "RGBA":
        image = image.convert("RGBA")
    else:
        image = image.convert("RGB")

    array = np.array(image, dtype=np.float32) / 255.0
    if array.ndim == 2:
        array = np.stack([array, array, array], axis=-1)
    elif array.ndim == 3 and array.shape[-1] not in (3, 4):
        array = array[..., :3]
    return torch.from_numpy(array)


def _resize_square(image: Image.Image, size: int) -> Image.Image:
    if image.size == (size, size):
        return image
    return image.resize((size, size), Image.LANCZOS)


def _round_to_multiple(value: float, multiple: int) -> int:
    return max(multiple, int(round(value / multiple)) * multiple)


def _resize_long_side(image: Image.Image, target: int) -> Image.Image:
    width, height = image.size
    long_side = max(width, height)
    if long_side <= 0:
        return image
    scale = float(target) / float(long_side)
    new_width = _round_to_multiple(width * scale, 32)
    new_height = _round_to_multiple(height * scale, 32)
    if (new_width, new_height) == image.size:
        return image
    return image.resize((new_width, new_height), Image.LANCZOS)


def _parse_color_code(color_value: str) -> tuple[int, int, int]:
    text = _unwrap_quotes(color_value).lstrip("#")
    if len(text) == 6:
        return tuple(int(text[index : index + 2], 16) for index in (0, 2, 4))
    if len(text) == 8:
        return tuple(int(text[index : index + 2], 16) for index in (0, 2, 4))
    raise ValueError(f"Invalid color code: {color_value!r}")


def _apply_mask_postprocess(mask: Image.Image, sensitivity: float, blur: int, offset: int) -> Image.Image:
    mask = mask.convert("L")
    sensitivity = float(max(0.0, min(1.0, sensitivity)))

    if sensitivity != 1.0:
        mask_np = np.array(mask, dtype=np.float32) / 255.0
        mask_np = _clamp01(mask_np * (1.0 + (1.0 - sensitivity)))
        mask = Image.fromarray((mask_np * 255.0).astype(np.uint8), mode="L")

    if blur > 0:
        mask = mask.filter(ImageFilter.GaussianBlur(radius=float(blur)))

    if offset > 0:
        for _ in range(int(offset)):
            mask = mask.filter(ImageFilter.MaxFilter(3))
    elif offset < 0:
        for _ in range(int(-offset)):
            mask = mask.filter(ImageFilter.MinFilter(3))

    return mask


def _compose_output(original: Image.Image, mask: Image.Image, background_mode: str, background_color: str) -> Image.Image:
    rgba = original.convert("RGBA")
    r, g, b, _ = rgba.split()
    foreground = Image.merge("RGBA", (r, g, b, mask.convert("L")))

    if background_mode == "Alpha":
        return foreground

    if background_mode == "黑色":
        background_rgb = (0, 0, 0)
    elif background_mode == "白色":
        background_rgb = (255, 255, 255)
    else:
        background_rgb = _parse_color_code(background_color)

    background = Image.new("RGBA", original.size, (*background_rgb, 255))
    return Image.alpha_composite(background, foreground).convert("RGB")


def _background_mode_to_internal(background_mode: str) -> str:
    if background_mode == "透明":
        return "Alpha"
    return background_mode


def _multiply_masks(mask_a: Image.Image, mask_b: Image.Image) -> Image.Image:
    a = np.asarray(mask_a.convert("L"), dtype=np.float32) / 255.0
    b = np.asarray(mask_b.convert("L"), dtype=np.float32) / 255.0
    return Image.fromarray((_clamp01(a * b) * 255.0).astype(np.uint8), mode="L")


def _union_masks(masks: list[Image.Image], size: tuple[int, int]) -> Image.Image:
    if not masks:
        return Image.new("L", size, 0)
    merged = np.zeros((size[1], size[0]), dtype=np.float32)
    for mask in masks:
        mask_arr = np.asarray(mask.convert("L"), dtype=np.float32) / 255.0
        merged = np.maximum(merged, mask_arr)
    return Image.fromarray((_clamp01(merged) * 255.0).astype(np.uint8), mode="L")


def _mask_area(mask: Image.Image) -> int:
    return int(np.count_nonzero(np.asarray(mask.convert("L")) > 0))


def _normalize_sam_resolution(value: int) -> int:
    value = max(672, min(1344, int(value)))
    return max(112, int(round(value / 112.0)) * 112)


def _find_sam3_checkpoint() -> str | None:
    candidate_dirs = [
        LX_SEMANTIC_MODEL_ROOT,
        os.path.join(folder_paths.models_dir, "SAM3"),
        os.path.join(folder_paths.models_dir, "sam3"),
    ]
    candidate_names = ["sam3.1_multiplex.pt"]
    for directory in candidate_dirs:
        for filename in candidate_names:
            path = os.path.join(directory, filename)
            if os.path.isfile(path):
                return path

    mirror_repo_ids = [
        "AEmotionStudio/sam3.1",
        "research21/sam3.1",
    ]
    try:
        from huggingface_hub import hf_hub_download
    except Exception as exc:
        print(f"[LX SemanticCutout] huggingface_hub unavailable for SAM3.1 checkpoint download: {exc}")
        return None

    for repo_id in mirror_repo_ids:
        try:
            return hf_hub_download(repo_id=repo_id, filename="sam3.1_multiplex.pt")
        except Exception as exc:
            print(f"[LX SemanticCutout] SAM3.1 checkpoint unavailable from {repo_id}: {exc}")
    return None


def _is_path_under(path: str | None, root: str) -> bool:
    if not path:
        return False
    try:
        path_abs = os.path.abspath(path)
        root_abs = os.path.abspath(root)
        return os.path.commonpath([path_abs, root_abs]) == root_abs
    except Exception:
        return False


def _module_origin(module_name: str) -> str | None:
    module = sys.modules.get(module_name)
    if module is None:
        return None
    origin = getattr(module, "__file__", None)
    if origin:
        return os.path.abspath(str(origin))
    spec = getattr(module, "__spec__", None)
    origin = getattr(spec, "origin", None)
    return os.path.abspath(str(origin)) if origin else None


def _sam3_search_path_without_custom_nodes() -> list[str]:
    search_path: list[str] = []
    seen: set[str] = set()
    for entry in sys.path:
        probe = os.getcwd() if entry == "" else entry
        if _is_path_under(probe, CUSTOM_NODES_ROOT):
            continue
        key = os.path.abspath(probe)
        if key in seen:
            continue
        seen.add(key)
        search_path.append(entry)
    return search_path


def _find_external_sam3_spec():
    spec = importlib.machinery.PathFinder.find_spec("sam3", _sam3_search_path_without_custom_nodes())
    origin = getattr(spec, "origin", None) if spec else None
    if origin and not _is_path_under(origin, CUSTOM_NODES_ROOT):
        return spec
    return None


def _package_parent_from_spec(spec) -> str | None:
    locations = list(getattr(spec, "submodule_search_locations", None) or [])
    if locations:
        return os.path.dirname(os.path.abspath(locations[0]))
    origin = getattr(spec, "origin", None)
    if origin:
        return os.path.dirname(os.path.abspath(origin))
    return None


def _import_external_sam3():
    current_origin = _module_origin("sam3")
    if current_origin and not _is_path_under(current_origin, CUSTOM_NODES_ROOT):
        from sam3 import build_sam3_image_model
        from sam3.model.sam3_image_processor import Sam3Processor

        return build_sam3_image_model, Sam3Processor

    spec = _find_external_sam3_spec()
    if spec is None:
        if current_origin:
            raise RuntimeError(
                "检测到 sam3 来自其他 custom_nodes 插件："
                f"{current_origin}。LX 语义抠图不复用其他插件内置的 sam3，"
                "请在 ComfyUI 的 Python 环境中安装官方 sam3 包。"
            )
        raise RuntimeError("缺少官方 sam3 依赖，无法使用语义抠图。请先安装官方 sam3 包。")

    package_parent = _package_parent_from_spec(spec)
    removed_modules = {
        name: module
        for name, module in list(sys.modules.items())
        if name == "sam3" or name.startswith("sam3.")
    }
    if removed_modules:
        print(
            "[LX SemanticCutout] ignoring existing sam3 module from "
            f"{current_origin or 'unknown origin'} and using official sam3 from {spec.origin}"
        )
        for name in removed_modules:
            sys.modules.pop(name, None)

    original_path = list(sys.path)
    try:
        search_path = _sam3_search_path_without_custom_nodes()
        if package_parent and package_parent not in search_path:
            search_path.insert(0, package_parent)
        sys.path = search_path
        from sam3 import build_sam3_image_model
        from sam3.model.sam3_image_processor import Sam3Processor

        imported_origin = _module_origin("sam3")
        if _is_path_under(imported_origin, CUSTOM_NODES_ROOT):
            raise RuntimeError(f"sam3 导入到了其他 custom_nodes 插件：{imported_origin}")
        return build_sam3_image_model, Sam3Processor
    except Exception:
        for name in list(sys.modules):
            if name == "sam3" or name.startswith("sam3."):
                sys.modules.pop(name, None)
        sys.modules.update(removed_modules)
        raise
    finally:
        sys.path = original_path


def _find_package_file(package_name: str, filename: str) -> str | None:
    spec = importlib.util.find_spec(package_name)
    origin = getattr(spec, "origin", None) if spec else None
    if not origin:
        return None
    candidate = os.path.join(os.path.dirname(os.path.abspath(origin)), filename)
    return candidate if os.path.isfile(candidate) else None


def _find_sam3_bpe_path() -> str | None:
    filename = "bpe_simple_vocab_16e6.txt.gz"
    candidate_paths = [
        os.path.join(LX_SEMANTIC_MODEL_ROOT, "assets", filename),
        os.path.join(LX_SEMANTIC_MODEL_ROOT, filename),
        os.path.join(folder_paths.models_dir, "SAM3", "assets", filename),
        os.path.join(folder_paths.models_dir, "SAM3", filename),
        os.path.join(folder_paths.models_dir, "sam3", "assets", filename),
        os.path.join(folder_paths.models_dir, "sam3", filename),
    ]
    for path in candidate_paths:
        if os.path.isfile(path):
            return path

    for package_name in ("clip", "open_clip"):
        package_file = _find_package_file(package_name, filename)
        if package_file:
            return package_file
    return None


def _model_file_path(directory: str, filename: str) -> str:
    parts = filename.replace("\\", "/").split("/")
    return os.path.join(directory, *parts)


def _has_model_files(directory: str, filenames: list[str]) -> bool:
    return all(os.path.isfile(_model_file_path(directory, filename)) for filename in filenames)


def _find_model_file(directory: str, filenames: list[str]) -> str | None:
    for filename in filenames:
        path = _model_file_path(directory, filename)
        if os.path.isfile(path):
            return path
    return None


def _find_existing_model_dir(candidates: list[str], required_files: list[str]) -> str | None:
    for directory in candidates:
        if directory and _has_model_files(directory, required_files):
            return directory
    return None


def _find_existing_model_dir_with_weight(
    candidates: list[str],
    required_files: list[str],
    weight_candidates: list[str],
) -> str | None:
    for directory in candidates:
        if not directory:
            continue
        if not _has_model_files(directory, required_files):
            continue
        if _find_model_file(directory, weight_candidates):
            return directory
    return None


def _download_hf_files(repo_id: str, filenames: list[str], target_dir: str) -> str:
    try:
        from huggingface_hub import hf_hub_download
    except Exception as exc:
        raise RuntimeError(
            "Missing dependency huggingface_hub; install it or place the model files locally first."
        ) from exc

    _ensure_dir(target_dir)
    for filename in filenames:
        hf_hub_download(
            repo_id=repo_id,
            filename=filename,
            local_dir=target_dir,
            local_dir_use_symlinks=False,
        )
    return target_dir


def _download_hf_model_files(
    repo_id: str,
    required_files: list[str],
    weight_candidates: list[str],
    target_dir: str,
) -> str:
    _download_hf_files(repo_id, required_files, target_dir)

    errors: list[str] = []
    for filename in weight_candidates:
        try:
            _download_hf_files(repo_id, [filename], target_dir)
            return target_dir
        except Exception as exc:
            errors.append(f"{filename}: {exc}")

    detail = "; ".join(errors) if errors else "no weight candidates were configured"
    raise RuntimeError(f"Unable to download a usable weight file from {repo_id}: {detail}")


def _ensure_transformers_weights_config(directory: str, weight_filename: str | None) -> None:
    if not weight_filename:
        return

    config_path = os.path.join(directory, "config.json")
    if not os.path.isfile(config_path):
        return

    try:
        with open(config_path, "r", encoding="utf-8") as handle:
            config = json.load(handle)
    except Exception:
        return

    if config.get("transformers_weights") == weight_filename:
        return

    config["transformers_weights"] = weight_filename
    try:
        with open(config_path, "w", encoding="utf-8") as handle:
            json.dump(config, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
    except Exception:
        pass


def _download_url(url: str, target_path: str) -> str:
    import requests

    _ensure_dir(os.path.dirname(target_path))
    tmp_path = f"{target_path}.part"

    try:
        with requests.get(url, stream=True, timeout=(30, 300)) as response:
            response.raise_for_status()
            with open(tmp_path, "wb") as handle:
                for chunk in response.iter_content(chunk_size=1024 * 1024):
                    if chunk:
                        handle.write(chunk)
    except Exception:
        try:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
        except OSError:
            pass
        raise

    os.replace(tmp_path, target_path)
    return target_path


def _auto_model_root(name: str) -> str:
    return os.path.join(LX_MODEL_ROOT, name)


@dataclass(frozen=True)
class _TransformersModelSpec:
    repo_id: str
    filenames: list[str]
    legacy_dirs: list[str]
    weight_candidates: list[str]
    transformers_weights: str | None = None


@dataclass(frozen=True)
class _BEN2ModelSpec:
    repo_id: str
    filenames: list[str]
    legacy_dirs: list[str]
    weight_candidates: list[str]


@dataclass(frozen=True)
class _SemanticMaskCandidate:
    mask: Image.Image
    score: float
    area: int
    box: tuple[float, float, float, float] | None = None


MODEL_SPECS: dict[str, dict[str, Any]] = {
    "BEN2": {
        "kind": "ben2",
        "spec": _BEN2ModelSpec(
            repo_id="1038lab/BEN2",
            filenames=["BEN2.py"],
            legacy_dirs=[os.path.join(LEGACY_RMBG_ROOT, "BEN2"), LEGACY_REMBG_ROOT],
            weight_candidates=["BEN2_Base.pth"],
        ),
        "default_res": 1024,
        "input_mode": "long_side",
    },
    "RMBG-2.0": {
        "kind": "transformers",
        "spec": _TransformersModelSpec(
            repo_id="1038lab/RMBG-2.0",
            filenames=["birefnet.py", "BiRefNet_config.py", "config.json"],
            legacy_dirs=[os.path.join(LEGACY_RMBG_ROOT, "RMBG-2.0")],
            weight_candidates=["model.safetensors", "pytorch_model.bin"],
        ),
        "default_res": 1024,
        "input_mode": "square",
        "cuda_half": False,
    },
    "InSPyReNet": {
        "kind": "transparent_background",
        "spec": {
            "ckpt_url": "https://github.com/plemeri/transparent-background/releases/download/1.2.12/ckpt_base.pth",
            "legacy_dirs": [os.path.join(LEGACY_RMBG_ROOT, "inspyrenet")],
            "target_file": "ckpt_base.pth",
        },
        "default_res": 1024,
        "input_mode": "long_side",
    },
    "BiRefNet-Matting": {
        "kind": "transformers",
        "spec": _TransformersModelSpec(
            repo_id="1038lab/BiRefNet",
            filenames=["birefnet.py", "BiRefNet_config.py", "config.json"],
            legacy_dirs=[],
            weight_candidates=["BiRefNet-matting.safetensors"],
            transformers_weights="BiRefNet-matting.safetensors",
        ),
        "default_res": 1024,
        "input_mode": "square",
    },
    "BiRefNet-Dynamic": {
        "kind": "transformers",
        "spec": _TransformersModelSpec(
            repo_id="1038lab/BiRefNet",
            filenames=["birefnet.py", "BiRefNet_config.py", "config.json"],
            legacy_dirs=[],
            weight_candidates=["BiRefNet_dynamic.safetensors"],
            transformers_weights="BiRefNet_dynamic.safetensors",
        ),
        "default_res": 1024,
        "input_mode": "long_side",
    },
}

SEMANTIC_SELECTION_MODES = ["自动最佳", "最大主体", "全部目标", "指定编号", "分离输出"]
SEMANTIC_REFINE_MODELS = ["自动", "无", "RMBG-2.0", "BiRefNet-Dynamic", "BEN2"]
SEMANTIC_BACKGROUND_MODES = ["透明", "白色", "黑色", "自定义颜色"]


def _parse_target_indices(value: Any) -> list[int]:
    text = str(value or "").strip()
    if not text or text == "0":
        return []
    text = re.sub(r"\s*-\s*", "-", text)

    indices: list[int] = []
    for part in re.split(r"[,，\s]+", text):
        part = part.strip()
        if not part:
            continue
        if re.fullmatch(r"\d+\s*-\s*\d+", part):
            start_text, end_text = re.split(r"\s*-\s*", part, maxsplit=1)
            start = int(start_text)
            end = int(end_text)
            if start <= 0 or end <= 0 or end < start:
                raise RuntimeError(f"目标编号范围无效：{part}")
            indices.extend(range(start, end + 1))
        elif part.isdigit():
            index = int(part)
            if index <= 0:
                return []
            indices.append(index)
        else:
            raise RuntimeError(f"目标编号格式无效：{part}。可填写 1、1,3,5 或 2-4。")

    deduped: list[int] = []
    seen: set[int] = set()
    for index in indices:
        if index not in seen:
            seen.add(index)
            deduped.append(index)
    return deduped


def _semantic_candidate_center(candidate: _SemanticMaskCandidate) -> tuple[float, float]:
    if candidate.box is not None:
        x0, y0, x1, y1 = candidate.box
        return ((x0 + x1) * 0.5, (y0 + y1) * 0.5)

    mask_np = np.asarray(candidate.mask.convert("L")) > 0
    if not np.any(mask_np):
        return (float("inf"), float("inf"))
    ys, xs = np.where(mask_np)
    return ((float(xs.min()) + float(xs.max())) * 0.5, (float(ys.min()) + float(ys.max())) * 0.5)


def _rank_semantic_candidates_left_to_right(
    candidates: list[_SemanticMaskCandidate],
) -> list[_SemanticMaskCandidate]:
    return sorted(
        candidates,
        key=lambda item: (*_semantic_candidate_center(item), -float(item.score), -int(item.area)),
    )


def _pick_semantic_candidates_by_indices(
    candidates: list[_SemanticMaskCandidate],
    target_indices: list[int],
) -> list[_SemanticMaskCandidate]:
    picked: list[_SemanticMaskCandidate] = []
    for target_index in target_indices:
        index = int(target_index) - 1
        if index < 0 or index >= len(candidates):
            raise RuntimeError(f"目标编号超出范围：当前只有 {len(candidates)} 个候选目标。")
        picked.append(candidates[index])
    return picked


def _select_semantic_masks(
    candidates: list[_SemanticMaskCandidate],
    mode: str,
    target_indices: list[int],
    target_count: int,
    image_size: tuple[int, int],
) -> list[Image.Image]:
    if not candidates:
        raise RuntimeError("SAM 没有找到符合目标描述的区域。可以换成更简单的英文名词，或降低识别阈值。")

    ranked_by_score = sorted(candidates, key=lambda item: item.score, reverse=True)
    ranked_left_to_right = _rank_semantic_candidates_left_to_right(candidates)

    if mode == "最大主体":
        return [max(candidates, key=lambda item: item.area).mask]

    if mode in {"全部目标", "分离输出"}:
        selected = ranked_left_to_right
        if target_indices:
            selected = _pick_semantic_candidates_by_indices(ranked_left_to_right, target_indices)
        elif target_count > 0:
            selected = ranked_left_to_right[: int(target_count)]
        if mode == "分离输出":
            return [item.mask for item in selected]
        return [_union_masks([item.mask for item in selected], image_size)]

    if mode == "指定编号":
        if target_indices:
            selected = _pick_semantic_candidates_by_indices(ranked_left_to_right, target_indices)
        elif target_count > 0:
            selected = ranked_left_to_right[: int(target_count)]
        else:
            selected = _pick_semantic_candidates_by_indices(ranked_left_to_right, [1])
        return [_union_masks([item.mask for item in selected], image_size)]

    return [ranked_by_score[0].mask]


def _resolve_refine_model(refine_model: str) -> str | None:
    if refine_model == "无":
        return None
    if refine_model == "自动":
        return "BiRefNet-Dynamic"
    if refine_model not in MODEL_ORDER:
        raise RuntimeError(f"不支持的精修模型：{refine_model}")
    return refine_model


class _BaseBackend:
    def __init__(self, model_name: str):
        self.model_name = model_name
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        self.model = None
        self.model_dir: str | None = None
        self._lock = threading.Lock()

    def unload(self) -> None:
        with self._lock:
            if self.model is not None:
                try:
                    if hasattr(self.model, "cpu"):
                        self.model.cpu()
                except Exception:
                    pass
                del self.model
                self.model = None
            self.model_dir = None
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
            gc.collect()


def _patch_transformers_remote_model(model: Any) -> None:
    modules = model.modules() if hasattr(model, "modules") else []
    for module in modules:
        config = getattr(module, "config", None)
        if config is not None and not hasattr(config, "model_type"):
            setattr(config, "model_type", None)
        if config is not None and not hasattr(module, "all_tied_weights_keys"):
            setattr(module, "all_tied_weights_keys", {})


@contextmanager
def _transformers_remote_code_compat():
    try:
        import transformers.modeling_utils as modeling_utils
    except Exception:
        yield
        return

    original = getattr(modeling_utils, "get_model_conversion_mapping", None)
    if original is None:
        yield
        return

    def safe_get_model_conversion_mapping(model, *args, **kwargs):
        _patch_transformers_remote_model(model)
        try:
            return original(model, *args, **kwargs)
        except AttributeError as exc:
            if "model_type" not in str(exc):
                raise
            _patch_transformers_remote_model(model)
            return original(model, *args, **kwargs)

    modeling_utils.get_model_conversion_mapping = safe_get_model_conversion_mapping
    try:
        yield
    finally:
        modeling_utils.get_model_conversion_mapping = original


class _TransformersBackend(_BaseBackend):
    def _resolve_model_dir(self) -> str:
        spec: _TransformersModelSpec = MODEL_SPECS[self.model_name]["spec"]
        target_dir = _auto_model_root(self.model_name)
        existing = _find_existing_model_dir_with_weight(
            [target_dir, *spec.legacy_dirs],
            spec.filenames,
            spec.weight_candidates,
        )
        if existing:
            _ensure_transformers_weights_config(existing, spec.transformers_weights)
            return existing
        model_dir = _download_hf_model_files(spec.repo_id, spec.filenames, spec.weight_candidates, target_dir)
        _ensure_transformers_weights_config(model_dir, spec.transformers_weights)
        return model_dir

    def load(self) -> None:
        with self._lock:
            if self.model is not None:
                return
            if AutoModelForImageSegmentation is None:
                raise RuntimeError(
                    "缺少 transformers 依赖，无法加载 BiRefNet / RMBG-2.0。请先安装 requirements-full.txt。"
                )

            model_dir = self._resolve_model_dir()
            try:
                with _transformers_remote_code_compat():
                    model = AutoModelForImageSegmentation.from_pretrained(
                        model_dir,
                        trust_remote_code=True,
                        local_files_only=True,
                    )
                _patch_transformers_remote_model(model)
            except Exception as exc:
                raise RuntimeError(f"加载 {self.model_name} 失败：{exc}") from exc

            model.eval()
            if self.device == "cuda" and MODEL_SPECS[self.model_name].get("cuda_half", True):
                model = model.to(self.device).half()
            else:
                model = model.to(self.device)

            self.model = model
            self.model_dir = model_dir

    @staticmethod
    def _mask_tensor_score(tensor: torch.Tensor) -> tuple[int, int, int]:
        shape = tuple(int(dim) for dim in tensor.shape)
        if tensor.ndim >= 2:
            area = shape[-1] * shape[-2]
        else:
            area = 0

        single_channel = 0
        if tensor.ndim == 4 and (shape[1] == 1 or shape[-1] == 1):
            single_channel = 1
        elif tensor.ndim in (2, 3):
            single_channel = 1

        return (single_channel, area, tensor.ndim)

    @staticmethod
    def _extract_logits(outputs: Any) -> torch.Tensor:
        if torch.is_tensor(outputs):
            return outputs

        if isinstance(outputs, (list, tuple)):
            candidates: list[torch.Tensor] = []
            for item in outputs:
                try:
                    candidates.append(_TransformersBackend._extract_logits(item))
                except RuntimeError:
                    continue
            if candidates:
                return max(candidates, key=_TransformersBackend._mask_tensor_score)

        if isinstance(outputs, dict):
            for key in ("logits", "predictions", "output", "mask", "masks"):
                value = outputs.get(key)
                if value is None:
                    continue
                try:
                    return _TransformersBackend._extract_logits(value)
                except RuntimeError:
                    continue
            for value in outputs.values():
                try:
                    return _TransformersBackend._extract_logits(value)
                except RuntimeError:
                    continue

        for attr in ("logits", "predictions", "mask"):
            value = getattr(outputs, attr, None)
            if value is None:
                continue
            try:
                return _TransformersBackend._extract_logits(value)
            except RuntimeError:
                continue

        raise RuntimeError(f"无法识别 {outputs.__class__.__name__} 的输出格式")

    @staticmethod
    def _logits_to_masks(logits: torch.Tensor) -> torch.Tensor:
        if logits.ndim == 4:
            if logits.shape[1] == 1:
                logits = logits[:, 0]
            elif logits.shape[-1] == 1:
                logits = logits[..., 0]
            else:
                logits = logits[:, 0]

        if logits.ndim == 3:
            pass
        elif logits.ndim == 2:
            logits = logits.unsqueeze(0)
        else:
            raise RuntimeError(f"不支持的 mask 张量维度：{tuple(logits.shape)}")

        logits = logits.float()
        if float(logits.amin().item()) < -1e-4 or float(logits.amax().item()) > 1.0 + 1e-4:
            logits = torch.sigmoid(logits)
        return logits.clamp(0.0, 1.0).cpu()

    @staticmethod
    def _preprocess_image(image: Image.Image, size: int, input_mode: str) -> torch.Tensor:
        rgb = image.convert("RGB")
        resized = _resize_long_side(rgb, size) if input_mode == "long_side" else _resize_square(rgb, size)
        array = np.asarray(resized, dtype=np.float32) / 255.0
        array = (array - np.array([0.485, 0.456, 0.406], dtype=np.float32)) / np.array(
            [0.229, 0.224, 0.225], dtype=np.float32
        )
        array = np.transpose(array, (2, 0, 1))
        return torch.from_numpy(array)

    def _infer_masks(self, input_batch: torch.Tensor) -> torch.Tensor:
        if self.device == "cuda" and MODEL_SPECS[self.model_name].get("cuda_half", True):
            input_batch = input_batch.to(self.device).half()
        else:
            input_batch = input_batch.to(self.device)

        with torch.inference_mode():
            outputs = self.model(input_batch)

        logits = self._extract_logits(outputs)
        return self._logits_to_masks(logits)

    @staticmethod
    def _mask_tensor_to_pil(mask_tensor: torch.Tensor, original_size: tuple[int, int]) -> Image.Image:
        if mask_tensor.ndim == 3:
            mask_tensor = mask_tensor[0]
        mask_np = mask_tensor.numpy()
        mask_img = Image.fromarray((mask_np * 255.0).astype(np.uint8), mode="L")
        return mask_img.resize(original_size, Image.BICUBIC)

    def segment(self, images: list[Image.Image], process_res: int) -> list[Image.Image]:
        self.load()
        size = _normalize_resolution(process_res)
        input_mode = MODEL_SPECS[self.model_name].get("input_mode", "square")
        originals = [image.size for image in images]

        if input_mode == "long_side":
            result: list[Image.Image] = []
            for image, original_size in zip(images, originals):
                tensor = self._preprocess_image(image, size, input_mode).unsqueeze(0)
                masks = self._infer_masks(tensor)
                result.append(self._mask_tensor_to_pil(masks[0], original_size))
            return result

        batches = [self._preprocess_image(image, size, input_mode) for image in images]
        masks = self._infer_masks(torch.stack(batches, dim=0))

        result: list[Image.Image] = []
        for index, original_size in enumerate(originals):
            result.append(self._mask_tensor_to_pil(masks[index], original_size))
        return result


class _InspyreNetBackend(_BaseBackend):
    def _resolve_ckpt_path(self) -> str:
        spec = MODEL_SPECS[self.model_name]["spec"]
        target_dir = _auto_model_root(self.model_name)
        target_path = os.path.join(target_dir, spec["target_file"])
        if os.path.isfile(target_path):
            return target_path

        for legacy_dir in spec["legacy_dirs"]:
            legacy_path = os.path.join(legacy_dir, spec["target_file"])
            if os.path.isfile(legacy_path):
                return legacy_path

        return _download_url(spec["ckpt_url"], target_path)

    def load(self) -> None:
        with self._lock:
            if self.model is not None:
                return
            try:
                from transparent_background import Remover
            except Exception as exc:
                raise RuntimeError(
                    "缺少 transparent-background 依赖，无法加载 InSPyReNet。请先安装 requirements-full.txt。"
                ) from exc

            ckpt_path = self._resolve_ckpt_path()
            try:
                self.model = Remover(mode="base", jit=False, device=self.device, ckpt=ckpt_path, resize="static")
            except Exception as exc:
                raise RuntimeError(f"加载 InSPyReNet 失败：{exc}") from exc

            self.model_dir = os.path.dirname(ckpt_path)

    def segment(self, images: list[Image.Image], process_res: int) -> list[Image.Image]:
        self.load()
        target = _normalize_resolution(process_res)
        result: list[Image.Image] = []

        for image in images:
            original_size = image.size
            resized = _resize_long_side(image.convert("RGB"), target)
            with torch.inference_mode():
                output = self.model.process(resized, type="rgba")
            if not isinstance(output, Image.Image):
                output = Image.fromarray(np.array(output))
            alpha = output.convert("RGBA").getchannel("A")
            alpha = alpha.resize(original_size, Image.BICUBIC)
            result.append(alpha)

        return result


class _BEN2Backend(_BaseBackend):
    def _resolve_model_dir(self) -> str:
        spec: _BEN2ModelSpec = MODEL_SPECS[self.model_name]["spec"]
        target_dir = _auto_model_root(self.model_name)
        existing = _find_existing_model_dir_with_weight(
            [target_dir, *spec.legacy_dirs],
            spec.filenames,
            spec.weight_candidates,
        )
        if existing:
            return existing
        return _download_hf_model_files(spec.repo_id, spec.filenames, spec.weight_candidates, target_dir)

    def load(self) -> None:
        with self._lock:
            if self.model is not None:
                return

            model_dir = self._resolve_model_dir()
            model_path = os.path.join(model_dir, "BEN2.py")
            spec: _BEN2ModelSpec = MODEL_SPECS[self.model_name]["spec"]
            weights_path = _find_model_file(model_dir, spec.weight_candidates)
            if weights_path is None:
                raise RuntimeError(f"BEN2 weight file not found in {model_dir}")

            module_name = f"lx_auto_cutout_ben2_{abs(hash(model_path))}"
            spec = importlib.util.spec_from_file_location(module_name, model_path)
            if spec is None or spec.loader is None:
                raise RuntimeError(f"无法加载 BEN2 模块：{model_path}")

            module = importlib.util.module_from_spec(spec)
            sys.modules[module_name] = module
            try:
                spec.loader.exec_module(module)
            except Exception as exc:
                raise RuntimeError(f"导入 BEN2.py 失败：{exc}") from exc

            try:
                model = module.BEN_Base()
                model.loadcheckpoints(weights_path)
                model.eval()
                model.to(self.device)
            except Exception as exc:
                raise RuntimeError(f"初始化 BEN2 失败：{exc}") from exc

            self.model = model
            self.model_dir = model_dir

    def segment(self, images: list[Image.Image], process_res: int) -> list[Image.Image]:
        self.load()
        target = _normalize_resolution(process_res)
        results: list[Image.Image] = []

        chunk_size = 3
        for start in range(0, len(images), chunk_size):
            chunk = images[start : start + chunk_size]
            resized_chunk: list[Image.Image] = []
            original_sizes: list[tuple[int, int]] = []

            for image in chunk:
                original_sizes.append(image.size)
                resized_chunk.append(_resize_long_side(image.convert("RGB"), target).convert("RGBA"))

            with torch.inference_mode():
                foregrounds = self.model.inference(resized_chunk)
            if not isinstance(foregrounds, list):
                foregrounds = [foregrounds]

            for foreground, original_size in zip(foregrounds, original_sizes):
                if not isinstance(foreground, Image.Image):
                    foreground = Image.fromarray(np.array(foreground))
                if foreground.mode != "RGBA":
                    foreground = foreground.convert("RGBA")
                alpha = foreground.getchannel("A").resize(original_size, Image.BICUBIC)
                results.append(alpha)

        return results


def _build_backend(model_name: str) -> _BaseBackend:
    kind = MODEL_SPECS[model_name]["kind"]
    if kind == "transformers":
        return _TransformersBackend(model_name)
    if kind == "transparent_background":
        return _InspyreNetBackend(model_name)
    if kind == "ben2":
        return _BEN2Backend(model_name)
    raise RuntimeError(f"未知模型类型：{kind}")


_BACKEND_CACHE: dict[str, _BaseBackend] = {}
_BACKEND_CACHE_LOCK = threading.Lock()


def _get_shared_backend(model_name: str) -> _BaseBackend:
    with _BACKEND_CACHE_LOCK:
        backend = _BACKEND_CACHE.get(model_name)
        if backend is None:
            backend = _build_backend(model_name)
            _BACKEND_CACHE[model_name] = backend
        return backend


class _Sam3SemanticBackend:
    def __init__(self):
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        self.model = None
        self._processor_cls = None
        self._lock = threading.Lock()

    def unload(self) -> None:
        with self._lock:
            if self.model is not None:
                try:
                    if hasattr(self.model, "cpu"):
                        self.model.cpu()
                except Exception:
                    pass
                del self.model
                self.model = None
            self._processor_cls = None
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
            gc.collect()

    def load(self) -> None:
        with self._lock:
            if self.model is not None and self._processor_cls is not None:
                return
            try:
                build_sam3_image_model, Sam3Processor = _import_external_sam3()
            except Exception as exc:
                raise RuntimeError(f"缺少官方 sam3 依赖，无法使用语义抠图：{exc}") from exc

            bpe_path = _find_sam3_bpe_path()
            if bpe_path is None:
                raise RuntimeError(
                    "缺少 SAM3 BPE 词表 bpe_simple_vocab_16e6.txt.gz。"
                    "请把该文件放到 ComfyUI/models/LX/semantic_cutout/assets/ 下，"
                    "或安装包含该词表的 clip/open_clip 包。"
                )
            checkpoint_path = _find_sam3_checkpoint()
            if checkpoint_path is None:
                raise RuntimeError(
                    "缺少 SAM3.1 权重 sam3.1_multiplex.pt。"
                    "请把它放到 ComfyUI/models/LX/semantic_cutout/ 下，"
                    "或确认 SAM3.1 镜像可访问后重试。"
                )
            try:
                model = build_sam3_image_model(
                    bpe_path=bpe_path,
                    device=self.device,
                    checkpoint_path=checkpoint_path,
                    load_from_HF=False,
                    enable_segmentation=True,
                )
            except Exception as exc:
                raise RuntimeError(f"SAM3.1 模型加载失败：{exc}") from exc

            model.eval()
            self.model = model
            self._processor_cls = Sam3Processor

    @staticmethod
    def _state_to_candidates(state: dict[str, Any], image_size: tuple[int, int]) -> list[_SemanticMaskCandidate]:
        masks = state.get("masks")
        if masks is None:
            masks = state.get("masks_logits")
        if masks is None:
            return []

        if masks.ndim == 4 and masks.shape[1] == 1:
            masks = masks[:, 0]
        elif masks.ndim == 4:
            masks = masks[:, 0]
        elif masks.ndim == 2:
            masks = masks.unsqueeze(0)

        scores = state.get("scores")
        boxes = state.get("boxes")
        candidates: list[_SemanticMaskCandidate] = []

        for index in range(int(masks.shape[0])):
            mask_tensor = masks[index].detach().float().cpu()
            if mask_tensor.ndim != 2:
                continue
            mask_np = mask_tensor.numpy()
            mask_max = float(mask_np.max()) if mask_np.size else 0.0
            if mask_max <= 1.0:
                mask_np = mask_np * 255.0
            mask_img = Image.fromarray((mask_np > 127.0).astype(np.uint8) * 255, mode="L")
            if mask_img.size != image_size:
                mask_img = mask_img.resize(image_size, Image.NEAREST)

            area = _mask_area(mask_img)
            if area <= 0:
                continue

            score = 0.0
            if scores is not None and index < int(scores.shape[0]):
                score = float(scores[index].detach().float().cpu().item())

            box = None
            if boxes is not None and index < int(boxes.shape[0]):
                box_values = boxes[index].detach().float().cpu().tolist()
                if len(box_values) >= 4:
                    box = (float(box_values[0]), float(box_values[1]), float(box_values[2]), float(box_values[3]))

            candidates.append(_SemanticMaskCandidate(mask=mask_img, score=score, area=area, box=box))

        return candidates

    def segment(
        self,
        image: Image.Image,
        prompt: str,
        process_res: int,
        confidence_threshold: float,
    ) -> list[_SemanticMaskCandidate]:
        self.load()
        processor = self._processor_cls(
            self.model,
            resolution=_normalize_sam_resolution(process_res),
            device=self.device,
            confidence_threshold=float(confidence_threshold),
        )
        with torch.inference_mode():
            state = processor.set_image(image.convert("RGB"))
            state = processor.set_text_prompt(prompt=prompt, state=state)
        candidates = self._state_to_candidates(state, image.size)
        summary = ", ".join(f"{i + 1}:{candidate.score:.2f}" for i, candidate in enumerate(sorted(candidates, key=lambda item: item.score, reverse=True)[:8]))
        print(f"[LX SemanticCutout] prompt={prompt!r}, candidates={len(candidates)}, scores=[{summary}]")
        return candidates


_SAM3_BACKEND: _Sam3SemanticBackend | None = None
_SAM3_BACKEND_LOCK = threading.Lock()


def _get_sam3_backend() -> _Sam3SemanticBackend:
    global _SAM3_BACKEND
    with _SAM3_BACKEND_LOCK:
        if _SAM3_BACKEND is None:
            _SAM3_BACKEND = _Sam3SemanticBackend()
        return _SAM3_BACKEND


class AutoCutout:
    DESCRIPTION = "使用 BEN2、RMBG-2.0、InSPyReNet 或 BiRefNet 变体自动生成抠图图像和遮罩。"
    SEARCH_ALIASES = [
        "lx",
        "LX",
        "灵犀",
        "自动抠图",
        "LX自动抠图",
        "LX_自动抠图",
        "抠图",
        "去背景",
        "背景移除",
        "Remove Background",
        "Auto Cutout",
        "RMBG",
    ]

    def __init__(self):
        self._lock = threading.Lock()

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "图像": ("IMAGE",),
                "模型": (MODEL_ORDER, {"default": "InSPyReNet"}),
                "处理分辨率": (
                    "INT",
                    {
                        "default": 1024,
                        "min": 256,
                        "max": 2048,
                        "step": 32,
                        "display": "number",
                        "tooltip": "模型输入分辨率。通常 1024 足够，图更大时可提高。",
                    },
                ),
                "灵敏度": (
                    "FLOAT",
                    {
                        "default": 1.0,
                        "min": 0.0,
                        "max": 1.0,
                        "step": 0.01,
                        "display": "number",
                        "tooltip": "1.0 接近原始模型输出，往下会稍微放大前景。",
                    },
                ),
                "遮罩模糊": (
                    "INT",
                    {
                        "default": 0,
                        "min": 0,
                        "max": 64,
                        "step": 1,
                        "display": "number",
                        "tooltip": "柔化边缘，通常 0-5 就够用。",
                    },
                ),
                "遮罩偏移": (
                    "INT",
                    {
                        "default": 0,
                        "min": -20,
                        "max": 20,
                        "step": 1,
                        "display": "number",
                        "tooltip": "正数扩张，负数收缩。",
                    },
                ),
                "输出背景": (
                    ["Alpha", "黑色", "白色", "自定义颜色"],
                    {
                        "default": "Alpha",
                        "tooltip": "Alpha 输出透明背景；黑色/白色适合预览；自定义颜色使用下面的颜色值。",
                    },
                ),
                "背景颜色": (
                    "COLOR",
                    {
                        "default": "#222222",
                        "placeholder": "#222222",
                        "tooltip": "仅在输出背景为“自定义颜色”时生效。",
                    },
                ),
            },
        }

    RETURN_TYPES = ("IMAGE", "MASK")
    RETURN_NAMES = ("图像", "遮罩")
    FUNCTION = "remove_background"
    CATEGORY = LX_IMAGE_CATEGORY

    def _switch_backend(self, model_name: str) -> _BaseBackend:
        with self._lock:
            backend = _get_shared_backend(model_name)
        backend.load()
        return backend

    def remove_background(
        self,
        图像: torch.Tensor,
        模型: str,
        处理分辨率: int,
        灵敏度: float,
        遮罩模糊: int,
        遮罩偏移: int,
        输出背景: str,
        背景颜色: str,
    ):
        if 模型 not in MODEL_ORDER:
            raise RuntimeError(f"不支持的模型：{模型}")

        backend = self._switch_backend(模型)
        pil_images = _image_batch_to_pils(图像)
        raw_masks = backend.segment(pil_images, 处理分辨率)

        if len(raw_masks) != len(pil_images):
            raise RuntimeError(
                f"模型 {模型} 返回的 mask 数量不匹配：{len(raw_masks)} != {len(pil_images)}"
            )

        output_images: list[torch.Tensor] = []
        output_masks: list[torch.Tensor] = []

        for source_image, raw_mask in zip(pil_images, raw_masks):
            mask = _apply_mask_postprocess(raw_mask, 灵敏度, int(遮罩模糊), int(遮罩偏移))
            image = _compose_output(source_image, mask, 输出背景, 背景颜色)
            output_images.append(_pil_to_image_tensor(image))
            output_masks.append(_pil_to_mask_tensor(mask))

        image_batch = torch.stack(output_images, dim=0).float()
        mask_batch = torch.stack(output_masks, dim=0).float()
        return (image_batch, mask_batch)


class SemanticCutout:
    DESCRIPTION = "使用 SAM 语义定位目标，再可选使用 RMBG / BiRefNet / BEN2 精修边缘，输出抠图图像和遮罩。"
    SEARCH_ALIASES = [
        "lx",
        "LX",
        "灵犀",
        "语义抠图",
        "LX语义抠图",
        "语义分割",
        "SAM",
        "SAM3",
        "SAM3.1",
        "Semantic Cutout",
    ]

    def __init__(self):
        self._lock = threading.Lock()

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "图像": ("IMAGE",),
                "目标描述": (
                    "STRING",
                    {
                        "default": "",
                        "multiline": True,
                        "placeholder": "Describe the concept, e.g. person, hair, white dress",
                        "tooltip": "建议使用英文名词或短语，例如 person、hair、white dress、red shoes。",
                    },
                ),
                "目标选择": (
                    SEMANTIC_SELECTION_MODES,
                    {
                        "default": "自动最佳",
                        "tooltip": "自动最佳按置信度选择；最大主体按面积选择；编号默认按画面从左到右排序。",
                    },
                ),
                "目标编号": (
                    "STRING",
                    {
                        "default": "",
                        "multiline": False,
                        "placeholder": "1 或 1,3,5 或 2-4",
                        "tooltip": "支持单个或多个编号，例如 1、1,3,5、2-4。填写编号时优先使用编号，忽略目标数量。",
                    },
                ),
                "目标数量": (
                    "INT",
                    {
                        "default": 0,
                        "min": 0,
                        "max": 128,
                        "step": 1,
                        "display": "number",
                        "tooltip": "0 表示不限制。目标编号为空或 0 时，用于限制全部目标/指定编号/分离输出的最多目标数。",
                    },
                ),
                "精修模型": (
                    SEMANTIC_REFINE_MODELS,
                    {
                        "default": "自动",
                        "tooltip": "自动会优先使用 BiRefNet-Dynamic。选择“无”时直接使用 SAM 遮罩。",
                    },
                ),
                "处理分辨率": (
                    "INT",
                    {
                        "default": 1008,
                        "min": 672,
                        "max": 1344,
                        "step": 112,
                        "display": "number",
                        "tooltip": "SAM 语义定位分辨率。更高更慢、更占显存。",
                    },
                ),
                "识别阈值": (
                    "FLOAT",
                    {
                        "default": 0.35,
                        "min": 0.05,
                        "max": 0.95,
                        "step": 0.01,
                        "display": "number",
                        "tooltip": "越低候选越多，越高候选越少。",
                    },
                ),
                "遮罩扩张": (
                    "INT",
                    {
                        "default": 0,
                        "min": 0,
                        "max": 64,
                        "step": 1,
                        "display": "number",
                        "tooltip": "先扩大 SAM 语义区域，再与精修 alpha 融合，避免边缘被切掉。",
                    },
                ),
                "遮罩模糊": (
                    "INT",
                    {
                        "default": 0,
                        "min": 0,
                        "max": 64,
                        "step": 1,
                        "display": "number",
                    },
                ),
                "遮罩偏移": (
                    "INT",
                    {
                        "default": 0,
                        "min": -20,
                        "max": 20,
                        "step": 1,
                        "display": "number",
                    },
                ),
                "卸载模型": (
                    "BOOLEAN",
                    {
                        "default": False,
                        "tooltip": "低显存时打开；每次运行后释放 SAM3.1 和本次使用的精修模型。",
                    },
                ),
                "输出背景": (
                    SEMANTIC_BACKGROUND_MODES,
                    {
                        "default": "透明",
                    },
                ),
                "背景颜色": (
                    "COLOR",
                    {
                        "default": "#222222",
                        "placeholder": "#222222",
                    },
                ),
            },
        }

    RETURN_TYPES = ("IMAGE", "MASK")
    RETURN_NAMES = ("图像", "遮罩")
    FUNCTION = "semantic_cutout"
    CATEGORY = LX_IMAGE_CATEGORY

    def semantic_cutout(self, **kwargs):
        image_tensor = kwargs["图像"]
        prompt = str(kwargs.get("目标描述", "")).strip()
        if not prompt:
            raise RuntimeError("目标描述不能为空。建议使用英文名词或短语，例如 person、hair、white dress。")

        selection_mode = str(kwargs.get("目标选择", "自动最佳"))
        target_indices = _parse_target_indices(kwargs.get("目标编号", ""))
        target_count = int(kwargs.get("目标数量", 0))
        refine_choice = str(kwargs.get("精修模型", "自动"))
        process_res = int(kwargs.get("处理分辨率", 1008))
        confidence_threshold = float(kwargs.get("识别阈值", 0.35))
        mask_expand = int(kwargs.get("遮罩扩张", 0))
        mask_blur = int(kwargs.get("遮罩模糊", 0))
        mask_offset = int(kwargs.get("遮罩偏移", 0))
        background_mode = _background_mode_to_internal(str(kwargs.get("输出背景", "透明")))
        background_color = str(kwargs.get("背景颜色", "#222222"))
        unload_model = bool(kwargs.get("卸载模型", False))

        pil_images = _image_batch_to_pils(image_tensor)
        sam_backend = _get_sam3_backend()
        used_refine_backend: _BaseBackend | None = None

        try:
            semantic_masks_by_image: list[list[Image.Image]] = []
            for source_image in pil_images:
                candidates = sam_backend.segment(source_image, prompt, process_res, confidence_threshold)
                semantic_masks = _select_semantic_masks(
                    candidates,
                    selection_mode,
                    target_indices,
                    target_count,
                    source_image.size,
                )
                semantic_masks_by_image.append(semantic_masks)

            refine_model = _resolve_refine_model(refine_choice)
            refine_masks: list[Image.Image] | None = None
            if refine_model is not None:
                try:
                    used_refine_backend = _get_shared_backend(refine_model)
                    used_refine_backend.load()
                    refine_masks = used_refine_backend.segment(pil_images, _normalize_resolution(process_res))
                    if len(refine_masks) != len(pil_images):
                        raise RuntimeError(
                            f"精修模型 {refine_model} 返回的 mask 数量不匹配：{len(refine_masks)} != {len(pil_images)}"
                        )
                except Exception as exc:
                    if refine_choice == "自动":
                        print(f"[LX SemanticCutout] 自动精修失败，改用 SAM 遮罩直接输出：{exc}")
                        refine_masks = None
                    else:
                        raise

            output_images: list[torch.Tensor] = []
            output_masks: list[torch.Tensor] = []

            for image_index, source_image in enumerate(pil_images):
                for semantic_mask in semantic_masks_by_image[image_index]:
                    semantic_gate = _apply_mask_postprocess(semantic_mask, 1.0, 0, mask_expand)
                    if refine_masks is not None:
                        mask = _multiply_masks(refine_masks[image_index], semantic_gate)
                    else:
                        mask = semantic_gate
                    mask = _apply_mask_postprocess(mask, 1.0, mask_blur, mask_offset)
                    image = _compose_output(source_image, mask, background_mode, background_color)
                    output_images.append(_pil_to_image_tensor(image))
                    output_masks.append(_pil_to_mask_tensor(mask))

            image_batch = torch.stack(output_images, dim=0).float()
            mask_batch = torch.stack(output_masks, dim=0).float()
            return (image_batch, mask_batch)
        finally:
            if unload_model:
                sam_backend.unload()
                if used_refine_backend is not None:
                    used_refine_backend.unload()


NODE_CLASS_MAPPINGS = {
    "AutoCutout": AutoCutout,
    "SemanticCutout": SemanticCutout,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "SemanticCutout": "语义抠图",
    "AutoCutout": "自动抠图",
}
