# -*- coding: utf-8 -*-
"""Boogu image edit conditioning node."""

import math
import re

import torch

import comfy.model_management
import comfy.utils
import node_helpers

from ..categories import LX_IMAGE_EDIT_CATEGORY


MAX_IMAGES = 3
MAX_RESOLUTION = 16384
MAX_BATCH = 64
IMAGE_COUNT_CHOICES = [f"{index}_image" for index in range(1, MAX_IMAGES + 1)]
VL_TOTAL_PIXELS = 384 * 384
REF_LATENT_TOTAL_PIXELS = 1024 * 1024

BOOGU_DROP_SYSTEM = (
    "Describe the key features of the input image (color, shape, size, texture, objects, background), "
    "then explain how the user's text instruction should alter or modify the image. Generate a new image "
    "that meets the user's requirements while maintaining consistency with the original input where appropriate."
)

CHINESE_NUMERALS = {
    1: "\u4e00",
    2: "\u4e8c",
    3: "\u4e09",
}


def _parse_image_count(value):
    match = re.search(r"\d+", str(value or ""))
    if not match:
        return 1
    return max(1, min(MAX_IMAGES, int(match.group(0))))


def _snap_dimension(value):
    dimension = int(value or 1024)
    dimension = max(16, min(MAX_RESOLUTION, dimension))
    return max(16, round(dimension / 16.0) * 16)


def _normalize_prompt_image_refs(prompt):
    text = str(prompt or "")
    for index in range(MAX_IMAGES, 0, -1):
        cn = CHINESE_NUMERALS[index]
        replacement = f"Picture {index}"
        patterns = [
            rf"\u7b2c\s*{cn}\s*\u5f20\s*(?:\u56fe\u50cf|\u56fe\u7247|\u56fe)?",
            rf"\u7b2c\s*{index}\s*\u5f20\s*(?:\u56fe\u50cf|\u56fe\u7247|\u56fe)?",
            rf"(?:\u56fe\u50cf|\u56fe\u7247|\u56fe)\s*{cn}",
            rf"(?:\u56fe\u50cf|\u56fe\u7247|\u56fe)\s*{index}(?!\d)",
            rf"\bimage\s*{index}\b",
            rf"\bpicture\s*{index}\b",
        ]
        for pattern in patterns:
            text = re.sub(pattern, replacement, text, flags=re.IGNORECASE)
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


def _resize_to_total_pixels(image, total_pixels, round_to=None):
    samples = _to_rgb_image(image).movedim(-1, 1)
    _, _, height, width = samples.shape
    scale_by = math.sqrt(total_pixels / max(1, width * height))
    target_width = max(1, round(width * scale_by))
    target_height = max(1, round(height * scale_by))
    if round_to:
        target_width = max(round_to, round(target_width / round_to) * round_to)
        target_height = max(round_to, round(target_height / round_to) * round_to)
    resized = comfy.utils.common_upscale(samples, target_width, target_height, "area", "disabled")
    return resized.movedim(1, -1)[:, :, :, :3]


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


def _build_labeled_boogu_prompt(prompt, image_slots):
    image_prompt = ""
    for slot_index in image_slots:
        image_prompt += f"Picture {slot_index}: <|vision_start|><|image_pad|><|vision_end|>\n"

    return (
        f"<|im_start|>system\n{BOOGU_DROP_SYSTEM}<|im_end|>\n"
        f"<|im_start|>user\n{image_prompt}{prompt}<|im_end|>\n"
    )


def _encode_conditioning(clip, prompt, vl_images, ref_latents, image_slots):
    if vl_images:
        tokens = clip.tokenize(_build_labeled_boogu_prompt(prompt, image_slots), images=vl_images)
    else:
        tokens = clip.tokenize(prompt)

    conditioning = clip.encode_from_tokens_scheduled(tokens)
    if ref_latents:
        conditioning = node_helpers.conditioning_set_values(
            conditioning,
            {"reference_latents": ref_latents},
            append=True,
        )
    return conditioning


class LXBooguImageEdit:
    """Build Boogu image edit conditioning from one to three reference images."""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "clip": ("CLIP",),
                "vae": ("VAE",),
                "image1": ("IMAGE",),
                "prompt": ("STRING", {"multiline": True, "dynamicPrompts": True, "default": ""}),
                "image_count": (IMAGE_COUNT_CHOICES, {"default": "1_image"}),
                "width": ("INT", {"default": 1024, "min": 16, "max": MAX_RESOLUTION, "step": 16}),
                "height": ("INT", {"default": 1024, "min": 16, "max": MAX_RESOLUTION, "step": 16}),
                "batch_size": ("INT", {"default": 1, "min": 1, "max": MAX_BATCH, "step": 1}),
            },
            "optional": {
                "image2": ("IMAGE",),
                "image3": ("IMAGE",),
            },
        }

    RETURN_TYPES = ("CONDITIONING", "CONDITIONING", "LATENT")
    RETURN_NAMES = ("positive", "negative", "latent")
    FUNCTION = "encode"
    CATEGORY = f"{LX_IMAGE_EDIT_CATEGORY}/Boogu"
    DESCRIPTION = "Boogu Image Edit conditioning with up to three reference images."
    SEARCH_ALIASES = ["lx", "LX", "灵犀", "boogu", "boogu image edit", "image edit"]

    def encode(self, clip, vae, image1, **kwargs):
        prompt = _normalize_prompt_image_refs(kwargs.get("prompt", ""))
        image_count = _parse_image_count(kwargs.get("image_count", "1_image"))
        width = _snap_dimension(kwargs.get("width", 1024))
        height = _snap_dimension(kwargs.get("height", 1024))
        batch_size = int(kwargs.get("batch_size", 1))

        images = [(1, image1)]
        for index in range(2, image_count + 1):
            image = kwargs.get(f"image{index}")
            if image is not None:
                images.append((index, image))

        ref_latents = []
        vl_images = []
        image_slots = []

        for slot_index, image in images:
            vl_images.append(_resize_to_total_pixels(image, VL_TOTAL_PIXELS))
            ref_image = _resize_to_total_pixels(image, REF_LATENT_TOTAL_PIXELS, round_to=16)
            ref_latents.append(vae.encode(ref_image))
            image_slots.append(slot_index)

        positive = _encode_conditioning(clip, prompt, vl_images, ref_latents, image_slots)
        negative = _encode_conditioning(clip, "", [], ref_latents, [])

        if image1 is not None:
            latent_image = _resize_image(image1, width, height, "lanczos", "center")
            main_latent = vae.encode(latent_image)
        else:
            main_latent = _encode_empty_latent(vae, width, height)

        latent = {"samples": main_latent}

        if batch_size > 1 or latent["samples"].shape[0] != batch_size:
            positive = positive * batch_size
            negative = negative * batch_size
            latent = _repeat_latent_to_batch(latent, batch_size)

        return (positive, negative, latent)
