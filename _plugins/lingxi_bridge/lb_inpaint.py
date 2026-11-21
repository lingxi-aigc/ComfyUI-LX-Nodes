# -*- coding: utf-8 -*-
from __future__ import annotations

import base64
import hashlib
import json
import os
import time
from io import BytesIO
from typing import Any

import comfy.utils  # type: ignore[reportMissingImports]
import torch
from PIL import Image, ImageChops, ImageFilter, ImageOps
from comfy_execution.graph_utils import ExecutionBlocker  # type: ignore[reportMissingImports]

from ..categories import LX_RELAY_CATEGORY
from .lb_cache_paths import get_cache_dir
from .lb_config import API_PATHS, get_current_base_url
from .lb_image import (
    GPT_IMAGE2_MAX_EDGE,
    GPT_IMAGE2_MAX_PIXELS,
    GPT_IMAGE2_MODERATIONS,
    GPT_IMAGE2_QUALITIES,
    LingxiBridgeImage,
)
from .lb_utils import pil2tensor, tensor2pil


MASK_MODES = ["白色区域修改", "黑色区域修改"]
PRESERVE_OPTIONS = ["true", "false"]
CACHE_DIR = get_cache_dir("inpaint_api")
API_CACHE_VERSION = "lx_inpaint_api_v3"


def _clean_str(value: object) -> str:
    return "" if value is None else str(value).strip()


def _clip(value: object, limit: int = 1200) -> str:
    text = "" if value is None else str(value)
    return text if len(text) <= limit else text[:limit] + "..."


def _parse_info(value: object) -> dict[str, Any]:
    if not isinstance(value, str) or not value.strip():
        return {}
    try:
        data = json.loads(value)
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _tensor_to_first_pil(image: torch.Tensor) -> Image.Image:
    return tensor2pil(image)[0].convert("RGB")


def _mask_to_pil(mask: torch.Tensor, size: tuple[int, int]) -> Image.Image:
    t = mask.detach().cpu()
    if t.ndim == 3:
        # ComfyUI MASK is usually (B, H, W). Use the first mask.
        t = t[0]
    elif t.ndim == 4:
        t = t[0]
        if t.ndim == 3:
            t = t[..., 0] if t.shape[-1] in (1, 3, 4) else t[0]
    if t.ndim != 2:
        raise ValueError(f"Unsupported mask tensor shape: {tuple(mask.shape)}")
    arr = t.numpy()
    if arr.size and float(arr.max()) > 1.0 + 1e-3:
        arr = arr / 255.0
    image = Image.fromarray((arr.clip(0.0, 1.0) * 255.0).astype("uint8"), mode="L")
    if image.size != size:
        image = image.resize(size, Image.LANCZOS)
    return image


def _multiple_of_16(value: int) -> int:
    return max(16, int(round(value / 16)) * 16)


def _api_canvas_size(size: tuple[int, int]) -> tuple[int, int]:
    width, height = size
    width = _multiple_of_16(width)
    height = _multiple_of_16(height)

    scale = min(GPT_IMAGE2_MAX_EDGE / max(width, height), 1.0)
    if width * height > GPT_IMAGE2_MAX_PIXELS:
        scale = min(scale, (GPT_IMAGE2_MAX_PIXELS / (width * height)) ** 0.5)
    if scale < 1.0:
        width = _multiple_of_16(max(16, int(width * scale)))
        height = _multiple_of_16(max(16, int(height * scale)))

    while width * height > GPT_IMAGE2_MAX_PIXELS:
        if width >= height:
            width -= 16
        else:
            height -= 16
    return max(16, width), max(16, height)


def _mask_area_percent(mask: Image.Image) -> float:
    histogram = mask.histogram()
    total = max(1, mask.width * mask.height * 255)
    weighted = sum(index * count for index, count in enumerate(histogram))
    return round(weighted * 100.0 / total, 3)


def _expand_mask(mask: Image.Image, pixels: int) -> Image.Image:
    pixels = max(0, int(pixels))
    if pixels <= 0:
        return mask
    return mask.filter(ImageFilter.MaxFilter(pixels * 2 + 1))


def _feather_mask(mask: Image.Image, pixels: int) -> Image.Image:
    pixels = max(0, int(pixels))
    if pixels <= 0:
        return mask
    return mask.filter(ImageFilter.GaussianBlur(radius=pixels))


def _mask_preview(mask: Image.Image) -> Image.Image:
    return Image.merge("RGB", (mask, mask, mask))


def _png_bytes(image: Image.Image) -> bytes:
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def _hash_image(image: Image.Image) -> str:
    rgb = image.convert("RGB")
    digest = hashlib.sha256()
    digest.update(f"{rgb.width}x{rgb.height}".encode("ascii"))
    digest.update(rgb.tobytes())
    return digest.hexdigest()


def _hash_mask(mask: Image.Image) -> str:
    gray = mask.convert("L")
    digest = hashlib.sha256()
    digest.update(f"{gray.width}x{gray.height}".encode("ascii"))
    digest.update(gray.tobytes())
    return digest.hexdigest()


def _sha_json(data: object) -> str:
    raw = json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8", errors="replace")).hexdigest()


def _cache_paths(cache_key: str) -> dict[str, str]:
    os.makedirs(CACHE_DIR, exist_ok=True)
    base = os.path.join(CACHE_DIR, cache_key[:32])
    return {
        "raw": base + "_raw.png",
        "meta": base + ".json",
    }


def _load_cache(cache_key: str) -> tuple[Image.Image, dict[str, Any]] | None:
    paths = _cache_paths(cache_key)
    if not all(os.path.isfile(paths[key]) for key in ("raw", "meta")):
        return None
    try:
        with Image.open(paths["raw"]) as image:
            raw = image.convert("RGB").copy()
        with open(paths["meta"], "r", encoding="utf-8") as f:
            meta = json.load(f)
        if not isinstance(meta, dict):
            meta = {}
        now = time.time()
        for path in paths.values():
            os.utime(path, (now, now))
        return raw, meta
    except Exception:
        return None


def _save_cache(
    cache_key: str,
    raw: Image.Image,
    api_payload: dict[str, Any],
) -> None:
    paths = _cache_paths(cache_key)
    raw.save(paths["raw"], format="PNG")
    with open(paths["meta"], "w", encoding="utf-8") as f:
        json.dump(api_payload, f, ensure_ascii=False, indent=2)
        f.write("\n")


class LingxiBridgeInpaint:
    CATEGORY = f"{LX_RELAY_CATEGORY}/单图生成"
    RETURN_TYPES = ("IMAGE", "IMAGE", "IMAGE", "STRING", "STRING")
    RETURN_NAMES = ("image", "raw_image", "mask_preview", "status", "status_json")
    FUNCTION = "inpaint"
    SIZE = (440, 520)
    SEARCH_ALIASES = ("lx", "LX", "灵犀", "灵犀局部编辑", "局部编辑", "局部重绘", "inpaint", "mask", "gpt-image2")

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "info": ("STRING", {"default": "", "forceInput": True}),
                "image": ("IMAGE",),
                "mask": ("MASK",),
                "prompt": ("STRING", {"multiline": True}),
                "quality": (GPT_IMAGE2_QUALITIES, {"default": "medium"}),
                "moderation": (GPT_IMAGE2_MODERATIONS, {"default": "low"}),
                "遮罩模式": (MASK_MODES, {"default": "白色区域修改"}),
                "保留外部": (PRESERVE_OPTIONS, {"default": "true"}),
                "边缘羽化": ("INT", {"default": 8, "min": 0, "max": 128, "step": 1}),
                "遮罩扩张": ("INT", {"default": 0, "min": 0, "max": 128, "step": 1}),
                "重新生成": ("BOOLEAN", {"default": False}),
            },
            "optional": {
                "image2": ("IMAGE",),
                "image3": ("IMAGE",),
                "image4": ("IMAGE",),
                "image5": ("IMAGE",),
            },
        }

    @classmethod
    def VALIDATE_INPUTS(cls, **kwargs):
        return True

    @classmethod
    def IS_CHANGED(cls, **kwargs):
        return time.time()

    def _error_outputs(
        self,
        source_image: Image.Image | None,
        mask_preview: Image.Image | None,
        code: str,
        message: str,
        payload: dict[str, Any],
    ):
        fallback = source_image or Image.new("RGB", (512, 512), (255, 255, 255))
        preview = mask_preview or Image.new("RGB", fallback.size, (0, 0, 0))
        payload.update({"status": "failed", "error": {"code": code, "message": message}})
        return (
            pil2tensor(fallback),
            pil2tensor(fallback),
            pil2tensor(preview),
            f"局部编辑失败：{message}",
            json.dumps(payload, ensure_ascii=False, indent=2),
        )

    def _call_api(
        self,
        node: LingxiBridgeImage,
        base_url: str,
        api_key: str,
        model: str,
        prompt: str,
        source: Image.Image,
        reference_images: list[Image.Image],
        api_mask_alpha: Image.Image,
        size: str,
        quality: str,
        moderation: str,
        deadline: float,
    ) -> tuple[torch.Tensor | ExecutionBlocker, str, str]:
        paths = API_PATHS.get("image_v1/images", {})
        url = f"{base_url}{paths.get('gpt_image2_edit', '/v1/images/edits')}"
        headers = {"Authorization": f"Bearer {api_key}", "Accept": "application/json"}
        data_dict = {
            "model": model,
            "prompt": prompt,
            "size": size,
            "n": "1",
            "quality": quality,
            "moderation": moderation,
        }

        # OpenAI-style edit masks use transparent pixels for the editable area.
        # Mirror alpha into RGB too, so OpenAI-compatible proxies that parse a
        # black/white mask instead of alpha still see black=edit, white=keep.
        keep_alpha = ImageOps.invert(api_mask_alpha.convert("L"))
        mask_rgba = Image.merge("RGBA", (keep_alpha, keep_alpha, keep_alpha, keep_alpha))
        files = [("image[]", ("image_1.png", BytesIO(_png_bytes(source)), "image/png"))]
        for index, reference_image in enumerate(reference_images[:4], start=2):
            files.append(("image[]", (f"image_{index}.png", BytesIO(_png_bytes(reference_image)), "image/png")))
        files.append(("mask", ("mask.png", BytesIO(_png_bytes(mask_rgba)), "image/png")))

        response = node._http_post(
            url,
            headers=headers,
            data=data_dict,
            files=files,
            timeout=node._gpt_image2_timeout("2K"),
            deadline=deadline,
        )
        if response.status_code != 200:
            node._err(
                f"gpt-image2 mask edit error: {response.status_code} - {response.text[:500]}",
                status_code=response.status_code,
                body_text=response.text,
                api_format="v1/images",
                model=model,
                base_url=base_url,
            )
            raise RuntimeError(f"gpt-image2 mask edit HTTP {response.status_code}")

        result = node._safe_json_response(response, "v1/images", model, base_url)
        img_type, img_data = node._extract_image(result)
        if img_type == "url":
            image_tensor = node._download_image(img_data, timeout=node._download_timeout("2K"), deadline=deadline)
            return image_tensor, node._success_response("url", img_data, model, "v1/images", "gpt-image2", size, "custom"), img_data
        image_tensor = node._base64_to_tensor(img_data)
        return image_tensor, node._success_response("base64", "", model, "v1/images", "gpt-image2", size, "custom"), ""

    def inpaint(
        self,
        info,
        image,
        mask,
        prompt,
        quality,
        moderation,
        遮罩模式,
        保留外部,
        边缘羽化,
        遮罩扩张,
        重新生成,
        image2=None,
        image3=None,
        image4=None,
        image5=None,
    ):
        started = time.time()
        pbar = comfy.utils.ProgressBar(100)
        pbar.update_absolute(0)

        mask_mode = 遮罩模式
        preserve_outside = 保留外部 == "true"
        feather_px = int(边缘羽化)
        mask_expand_px = int(遮罩扩张)
        regenerate = bool(重新生成)
        prompt_text = _clean_str(prompt)

        source = _tensor_to_first_pil(image)
        input_size = source.size
        reference_images = [
            _tensor_to_first_pil(extra)
            for extra in (image2, image3, image4, image5)
            if extra is not None
        ][:4]
        reference_sizes = [f"{ref.width}x{ref.height}" for ref in reference_images]
        api_mask_l = _mask_to_pil(mask, input_size)
        if mask_mode == "黑色区域修改":
            api_mask_l = ImageOps.invert(api_mask_l)
        compose_mask = _expand_mask(api_mask_l, mask_expand_px)
        blend_mask = _feather_mask(compose_mask, feather_px)
        preview = _mask_preview(blend_mask)

        status_payload: dict[str, Any] = {
            "type": "lx_inpaint_status",
            "version": 2,
            "status": "running",
            "request": {
                "prompt": prompt_text,
                "quality": quality,
                "moderation": moderation,
                "mask_mode": mask_mode,
                "preserve_outside": preserve_outside,
                "feather": feather_px,
                "mask_expand": mask_expand_px,
                "resize_policy": "自动适配",
                "regenerate": regenerate,
            },
            "image": {
                "input_size": f"{input_size[0]}x{input_size[1]}",
                "reference_count": len(reference_images),
                "reference_sizes": reference_sizes,
            },
            "mask": {
                "edit_area_percent": _mask_area_percent(api_mask_l),
                "compose_area_percent": _mask_area_percent(compose_mask),
            },
            "warnings": [],
        }

        parsed = _parse_info(info)
        node = LingxiBridgeImage()
        try:
            api_key = node._get_api_key(parsed.get("apikey", ""))
            api_base = _clean_str(parsed.get("api_base")).rstrip("/") or get_current_base_url().rstrip("/")
            api_format = _clean_str(parsed.get("api_format") or "v1/images")
            platform = _clean_str(parsed.get("platform") or "gpt-image2")
            model = _clean_str(parsed.get("model") or "gpt-image-2")
            status_payload["api"] = {
                "platform": platform,
                "api_base": api_base,
                "api_format": api_format,
                "model": model,
            }

            if not api_key:
                return self._error_outputs(source, preview, "NO_API_KEY", "API Key 为空或无效。", status_payload)
            if platform != "gpt-image2":
                return self._error_outputs(source, preview, "UNSUPPORTED_PLATFORM", "局部编辑节点仅支持 gpt-image2。", status_payload)
            if api_format != "v1/images":
                return self._error_outputs(source, preview, "UNSUPPORTED_API_FORMAT", "局部编辑节点仅支持 v1/images。", status_payload)
            if not _clean_str(prompt):
                return self._error_outputs(source, preview, "EMPTY_PROMPT", "提示词为空。", status_payload)
            if _mask_area_percent(api_mask_l) <= 0.01:
                status_payload["warnings"].append(
                    {"code": "MASK_TOO_SMALL", "message": "遮罩区域很小，模型可能不会明显修改。"}
                )

            api_size = _api_canvas_size(input_size)
            api_size_text = f"{api_size[0]}x{api_size[1]}"
            resized_for_api = api_size != input_size

            api_source = source if not resized_for_api else source.resize(api_size, Image.LANCZOS)
            api_mask = api_mask_l if not resized_for_api else api_mask_l.resize(api_size, Image.LANCZOS)
            api_blend_mask = blend_mask if not resized_for_api else blend_mask.resize(api_size, Image.LANCZOS)

            status_payload["image"].update(
                {
                    "api_size": api_size_text,
                    "resized_for_api": resized_for_api,
                }
            )
            status_payload["mask"].update(
                {
                    "input_size": f"{input_size[0]}x{input_size[1]}",
                    "api_size": api_size_text,
                    "api_mask_format": "PNG RGBA",
                    "api_mask_semantics": "transparent/black = edit, opaque/white = keep",
                }
            )

            api_key_hash = hashlib.sha256(api_key.encode("utf-8", errors="replace")).hexdigest()[:16]
            api_cache_key = _sha_json(
                {
                    "version": API_CACHE_VERSION,
                    "image": _hash_image(source),
                    "reference_images": [_hash_image(ref) for ref in reference_images],
                    "mask": _hash_mask(api_mask_l),
                    "prompt": prompt_text,
                    "quality": quality,
                    "moderation": moderation,
                    "mask_mode": mask_mode,
                    "api_size": api_size_text,
                    "platform": platform,
                    "api_base": api_base,
                    "api_format": api_format,
                    "model": model,
                    "api_key_hash": api_key_hash,
                }
            )
            status_payload["api_cache"] = {
                "enabled": True,
                "cache_key": api_cache_key,
                "api_key_hash": api_key_hash,
                "regenerate": regenerate,
                "hit": False,
            }
            status_payload["postprocess"] = {
                "preserve_outside": preserve_outside,
                "feather": feather_px,
                "mask_expand": mask_expand_px,
            }

            api_cache_hit = False
            response_data: dict[str, Any] = {}
            image_url = ""
            raw_api: Image.Image | None = None

            cached = None if regenerate else _load_cache(api_cache_key)
            if cached is not None:
                raw_api, cached_payload = cached
                api_cache_hit = True
                status_payload["api_cache"]["hit"] = True
                status_payload["api_cache"]["source"] = "disk"
                cached_response = cached_payload.get("response", {}) if isinstance(cached_payload, dict) else {}
                response_data = cached_response if isinstance(cached_response, dict) else _parse_info(cached_response)
                image_url = _clean_str(cached_payload.get("url", "")) if isinstance(cached_payload, dict) else ""
                pbar.update_absolute(85)
            else:
                pbar.update_absolute(20)
                deadline = time.time() + node._total_budget("2K")
                image_tensor, response_text, image_url = self._call_api(
                    node,
                    api_base,
                    api_key,
                    model,
                    prompt_text,
                    api_source,
                    reference_images,
                    api_mask,
                    api_size_text,
                    quality,
                    moderation,
                    deadline,
                )
                pbar.update_absolute(85)

                if not isinstance(image_tensor, torch.Tensor):
                    return self._error_outputs(source, preview, "NO_IMAGE", "接口没有返回图片。", status_payload)

                raw_api = _tensor_to_first_pil(image_tensor)
                response_data = _parse_info(response_text)
                api_payload = {
                    "version": API_CACHE_VERSION,
                    "created_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                    "url": image_url,
                    "response": response_data,
                    "raw_output_size": f"{raw_api.width}x{raw_api.height}",
                    "api_size": api_size_text,
                    "request": {
                        "prompt": prompt_text,
                        "quality": quality,
                        "moderation": moderation,
                        "mask_mode": mask_mode,
                        "reference_count": len(reference_images),
                        "reference_sizes": reference_sizes,
                    },
                    "api": status_payload["api"],
                }
                try:
                    _save_cache(api_cache_key, raw_api, api_payload)
                    status_payload["api_cache"]["saved"] = True
                except Exception as cache_exc:
                    status_payload["warnings"].append(
                        {
                            "code": "API_CACHE_SAVE_FAILED",
                            "message": f"接口结果缓存保存失败：{_clip(cache_exc, 300)}",
                        }
                    )

            if raw_api is None:
                return self._error_outputs(source, preview, "NO_IMAGE", "接口没有返回图片。", status_payload)

            raw_output_size = raw_api.size
            raw_for_compose = raw_api
            if raw_for_compose.size != api_source.size:
                status_payload["warnings"].append(
                    {
                        "code": "OUTPUT_SIZE_MISMATCH",
                        "message": "接口返回尺寸和请求尺寸不一致，已仅为合成流程临时缩放。",
                        "requested": api_size_text,
                        "output": f"{raw_for_compose.width}x{raw_for_compose.height}",
                    }
                )
                raw_for_compose = raw_for_compose.resize(api_source.size, Image.LANCZOS)

            if preserve_outside:
                final_api = Image.composite(raw_for_compose.convert("RGB"), api_source.convert("RGB"), api_blend_mask)
            else:
                final_api = raw_for_compose.convert("RGB")

            final = final_api if not resized_for_api else final_api.resize(input_size, Image.LANCZOS)
            raw_output = raw_api if not resized_for_api else raw_api.resize(input_size, Image.LANCZOS)

            pbar.update_absolute(100)
            status_payload.update(
                {
                    "status": "cached" if api_cache_hit else "generated",
                    "elapsed": round(time.time() - started, 3),
                    "url": image_url,
                    "response": response_data,
                }
            )
            status_payload["image"].update(
                {
                    "raw_output_size": f"{raw_output_size[0]}x{raw_output_size[1]}",
                    "final_size": f"{final.width}x{final.height}",
                    "preserve_outside_applied": preserve_outside,
                }
            )
            status_payload["api_cache"]["hit"] = api_cache_hit
            if api_cache_hit:
                status = (
                    f"局部编辑命中 API 缓存，已按当前后处理参数重新合成，用时 {status_payload['elapsed']} 秒。"
                    f" 原图 {input_size[0]}x{input_size[1]}，API {api_size_text}，输出 {final.width}x{final.height}。"
                )
            else:
                status = (
                    f"局部编辑完成，用时 {status_payload['elapsed']} 秒。"
                    f" 原图 {input_size[0]}x{input_size[1]}，API {api_size_text}，输出 {final.width}x{final.height}。"
                )
            return (
                pil2tensor(final),
                pil2tensor(raw_output),
                pil2tensor(preview),
                status,
                json.dumps(status_payload, ensure_ascii=False, indent=2),
            )
        except Exception as exc:
            message = _clip(str(exc), 800)
            return self._error_outputs(source, preview, "ERROR", message, status_payload)
