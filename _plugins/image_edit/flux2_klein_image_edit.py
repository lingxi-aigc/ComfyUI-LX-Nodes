# -*- coding: utf-8 -*-
"""Flux2 Klein image edit conditioning node."""

import math
import re

import torch

import comfy.model_management
import comfy.utils
import node_helpers

from ..categories import LX_IMAGE_EDIT_CATEGORY


MAX_IMAGES = 10
MAX_RESOLUTION = 16384
IMAGE_COUNT_CHOICES = [f"{index}_image" for index in range(1, MAX_IMAGES + 1)]
VL_SIZE_VALUES = (384, 512)
CHINESE_NUMERALS = {
    1: "一",
    2: "二",
    3: "三",
    4: "四",
    5: "五",
    6: "六",
    7: "七",
    8: "八",
    9: "九",
    10: "十",
}


def _parse_image_count(value):
    match = re.search(r"\d+", str(value or ""))
    if not match:
        return 2
    return max(1, min(MAX_IMAGES, int(match.group(0))))


def _parse_vl_size(value):
    size = int(value or VL_SIZE_VALUES[0])
    return VL_SIZE_VALUES[1] if size >= 448 else VL_SIZE_VALUES[0]


def _normalize_prompt_image_refs(prompt):
    text = str(prompt or "")
    for index in range(MAX_IMAGES, 0, -1):
        cn = CHINESE_NUMERALS[index]
        replacement = f"image{index}"
        patterns = [
            rf"第\s*{cn}\s*张\s*(?:图像|图片|图)?",
            rf"第\s*{index}\s*张\s*(?:图像|图片|图)?",
            rf"(?:图像|图片|图)\s*{cn}",
            rf"(?:图像|图片|图)\s*{index}(?!\d)",
        ]
        for pattern in patterns:
            text = re.sub(pattern, replacement, text)
    return text


def _to_rgb_image(image):
    if image.shape[-1] == 3:
        return image
    if image.shape[-1] > 3:
        return image[:, :, :, :3]
    if image.shape[-1] == 1:
        return image.repeat(1, 1, 1, 3)
    raise ValueError(f"Unsupported image channel count: {image.shape[-1]}")


def _resize_image(image, width, height, method, crop):
    samples = _to_rgb_image(image).movedim(-1, 1)
    resized = comfy.utils.common_upscale(samples, width, height, method, crop)
    return resized.movedim(1, -1)[:, :, :, :3]


def _make_vl_image(image, vl_size):
    samples = _to_rgb_image(image).movedim(-1, 1)
    _, _, height, width = samples.shape
    current_total = max(1, height * width)
    scale_by = math.sqrt((int(vl_size) * int(vl_size)) / current_total)
    vl_width = max(1, round(width * scale_by))
    vl_height = max(1, round(height * scale_by))
    resized = comfy.utils.common_upscale(samples, vl_width, vl_height, "area", "center")
    return resized.movedim(1, -1)[:, :, :, :3]


def _resize_mask(mask, width, height):
    if mask is None:
        return None
    if mask.dim() == 2:
        samples = mask.unsqueeze(0).unsqueeze(0)
    elif mask.dim() == 3:
        samples = mask.unsqueeze(1)
    elif mask.dim() == 4:
        samples = mask[:, :1, :, :]
    else:
        return None
    resized = comfy.utils.common_upscale(samples, width, height, "bilinear", "center")
    return resized.squeeze(1).clamp(0.0, 1.0)


def _encode_empty_latent(vae, width, height):
    device = comfy.model_management.intermediate_device()
    pixels = torch.zeros(1, height, width, 3, device=device)
    return vae.encode(pixels)


def _repeat_latent_to_batch(latent, batch_size):
    latent = latent.copy()
    latent["samples"] = comfy.utils.repeat_to_batch_size(latent["samples"], batch_size)
    if "noise_mask" in latent:
        latent["noise_mask"] = comfy.utils.repeat_to_batch_size(latent["noise_mask"], batch_size)
    return latent


class LXFlux2KleinImageEdit:
    """Build Flux2 Klein image edit conditioning from one or more reference images."""

    @classmethod
    def INPUT_TYPES(cls):
        optional = {
            "image1_mask": ("MASK",),
        }
        for index in range(1, MAX_IMAGES + 1):
            optional[f"image{index}"] = ("IMAGE",)

        return {
            "required": {
                "clip": ("CLIP",),
                "vae": ("VAE",),
                "prompt": ("STRING", {"multiline": True, "dynamicPrompts": True, "default": ""}),
                "image_count": (IMAGE_COUNT_CHOICES, {"default": "2_image"}),
                "width": ("INT", {"default": 1024, "min": 16, "max": MAX_RESOLUTION, "step": 16}),
                "height": ("INT", {"default": 1024, "min": 16, "max": MAX_RESOLUTION, "step": 16}),
                "VL size": (
                    "INT",
                    {
                        "default": 384,
                        "min": 384,
                        "max": 512,
                        "step": 128,
                        "tooltip": "参考图送入视觉语言编码器的尺寸。384 更快更省显存；512 更容易看清小字、logo 和复杂细节。",
                    },
                ),
                "batch_size": ("INT", {"default": 1, "min": 1, "max": 64, "step": 1}),
            },
            "optional": optional,
        }

    RETURN_TYPES = ("CONDITIONING", "CONDITIONING", "LATENT")
    RETURN_NAMES = ("positive", "negative", "latent")
    FUNCTION = "encode"
    CATEGORY = f"{LX_IMAGE_EDIT_CATEGORY}/Flux2"
    DESCRIPTION = "Flux2 Klein image edit conditioning with multi-image reference latent encoding."
    SEARCH_ALIASES = ["lx", "LX", "灵犀", "flux2", "klein", "image edit", "flux2 klein image edit", "图像编辑"]

    def encode(self, clip, vae, **kwargs):
        prompt = _normalize_prompt_image_refs(kwargs.get("prompt", kwargs.get("编辑指令", "")))
        image_count = _parse_image_count(kwargs.get("image_count", kwargs.get("图片数量", "2_image")))
        width = int(kwargs.get("width", kwargs.get("宽度", 1024)))
        height = int(kwargs.get("height", kwargs.get("高度", 1024)))
        vl_size = _parse_vl_size(kwargs.get("VL size", kwargs.get("VL尺寸", 384)))
        batch_size = int(kwargs.get("batch_size", kwargs.get("批量数量", 1)))

        images = []
        for index in range(1, image_count + 1):
            image = kwargs.get(f"image{index}", kwargs.get(f"图像{index}"))
            if image is not None:
                images.append((index, image))

        ref_latents = []
        vl_images = []
        prompt_prefix = ""
        main_latent = None

        for slot_index, image in images:
            vae_image = _resize_image(image, width, height, "lanczos", "center")
            ref_latent = vae.encode(vae_image)
            ref_latents.append(ref_latent)
            if slot_index == 1:
                main_latent = ref_latent

            vl_images.append(_make_vl_image(image, vl_size))
            prompt_prefix += f"image{slot_index}: <|vision_start|><|image_pad|><|vision_end|> "

        full_prompt = prompt_prefix + prompt
        positive_tokens = clip.tokenize(full_prompt, images=vl_images)
        positive = clip.encode_from_tokens_scheduled(positive_tokens)

        negative_tokens = clip.tokenize("")
        negative = clip.encode_from_tokens_scheduled(negative_tokens)

        if ref_latents:
            positive = node_helpers.conditioning_set_values(positive, {"reference_latents": ref_latents}, append=True)
            negative = node_helpers.conditioning_set_values(negative, {"reference_latents": ref_latents}, append=True)

        if main_latent is None:
            main_latent = ref_latents[0] if ref_latents else _encode_empty_latent(vae, width, height)

        latent = {"samples": main_latent}
        mask = _resize_mask(kwargs.get("image1_mask", kwargs.get("图像1遮罩")), width, height)
        if mask is not None and any(slot_index == 1 for slot_index, _ in images):
            latent["noise_mask"] = mask

        if batch_size > 1 or latent["samples"].shape[0] != batch_size:
            positive = positive * batch_size
            negative = negative * batch_size
            latent = _repeat_latent_to_batch(latent, batch_size)

        return (positive, negative, latent)
