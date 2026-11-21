# -*- coding: utf-8 -*-
"""Flux2 Kontext image edit conditioning node."""

import re

import torch

import comfy.model_management
import comfy.utils
import node_helpers

from ..categories import LX_IMAGE_EDIT_CATEGORY


MAX_IMAGES = 3
MAX_BATCH = 64
MAX_RESOLUTION = 16384
IMAGE_COUNT_CHOICES = [f"{index}_image" for index in range(1, MAX_IMAGES + 1)]

PREFERRED_KONTEXT_RESOLUTIONS = (
    (672, 1568),
    (688, 1504),
    (720, 1456),
    (752, 1392),
    (800, 1328),
    (832, 1248),
    (880, 1184),
    (944, 1104),
    (1024, 1024),
    (1104, 944),
    (1184, 880),
    (1248, 832),
    (1328, 800),
    (1392, 752),
    (1456, 720),
    (1504, 688),
    (1568, 672),
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
        replacement = f"image{index}"
        patterns = [
            rf"\u7b2c\s*{cn}\s*\u5f20\s*(?:\u56fe\u50cf|\u56fe\u7247|\u56fe)?",
            rf"\u7b2c\s*{index}\s*\u5f20\s*(?:\u56fe\u50cf|\u56fe\u7247|\u56fe)?",
            rf"(?:\u56fe\u50cf|\u56fe\u7247|\u56fe)\s*{cn}",
            rf"(?:\u56fe\u50cf|\u56fe\u7247|\u56fe)\s*{index}(?!\d)",
            rf"\bimage\s*{index}\b",
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


def _resize_image(image, width, height, method="lanczos", crop="center"):
    samples = _to_rgb_image(image).movedim(-1, 1)
    resized = comfy.utils.common_upscale(samples, width, height, method, crop)
    return resized.movedim(1, -1)[:, :, :, :3]


def _resize_kontext_reference(image):
    samples = _to_rgb_image(image).movedim(-1, 1)
    _, _, height, width = samples.shape
    aspect_ratio = width / max(1, height)
    _, target_width, target_height = min(
        (abs(aspect_ratio - ref_width / ref_height), ref_width, ref_height)
        for ref_width, ref_height in PREFERRED_KONTEXT_RESOLUTIONS
    )
    resized = comfy.utils.common_upscale(samples, target_width, target_height, "lanczos", "center")
    return resized.movedim(1, -1)[:, :, :, :3]


def _resize_mask(mask, width, height):
    if mask is None:
        return None
    if mask.dim() == 2:
        samples = mask.unsqueeze(0).unsqueeze(0)
    elif mask.dim() == 3:
        samples = mask.unsqueeze(1)
    elif mask.dim() == 4:
        if mask.shape[1] == 1:
            samples = mask
        elif mask.shape[-1] == 1:
            samples = mask.movedim(-1, 1)
        else:
            samples = mask[:, :1, :, :]
    else:
        return None
    resized = comfy.utils.common_upscale(samples, width, height, "bilinear", "center")
    return resized.clamp(0.0, 1.0)


def _make_empty_flux2_latent(width, height, batch_size):
    device = comfy.model_management.intermediate_device()
    samples = torch.zeros([batch_size, 128, height // 16, width // 16], device=device)
    return {"samples": samples}


def _repeat_latent_to_batch(latent, batch_size):
    latent = latent.copy()
    latent["samples"] = comfy.utils.repeat_to_batch_size(latent["samples"], batch_size)
    if "noise_mask" in latent:
        latent["noise_mask"] = comfy.utils.repeat_to_batch_size(latent["noise_mask"], batch_size)
    return latent


def _encode_text(clip, prompt):
    tokens = clip.tokenize(prompt)
    return clip.encode_from_tokens_scheduled(tokens)


def _attach_reference_latents(conditioning, ref_latents):
    if not ref_latents:
        return conditioning
    return node_helpers.conditioning_set_values(
        conditioning,
        {"reference_latents": ref_latents},
        append=True,
    )


class LXFlux2KontextImageEdit:
    """Build Flux2 Kontext image edit conditioning from one to three references."""

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
                "mask": ("MASK",),
                "image2": ("IMAGE",),
                "image3": ("IMAGE",),
            },
        }

    RETURN_TYPES = ("CONDITIONING", "CONDITIONING", "LATENT")
    RETURN_NAMES = ("positive", "negative", "latent")
    FUNCTION = "encode"
    CATEGORY = f"{LX_IMAGE_EDIT_CATEGORY}/Flux2"
    DESCRIPTION = "Flux2 Kontext image edit conditioning with up to three reference images."
    SEARCH_ALIASES = ["lx", "LX", "灵犀", "flux2", "kontext", "image edit", "flux2 kontext image edit"]

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
        for _, image in images:
            ref_image = _resize_kontext_reference(image)
            ref_latents.append(vae.encode(ref_image))

        positive = _attach_reference_latents(_encode_text(clip, prompt), ref_latents)
        negative = _attach_reference_latents(_encode_text(clip, ""), ref_latents)

        mask = _resize_mask(kwargs.get("mask"), width, height)
        if mask is None:
            latent = _make_empty_flux2_latent(width, height, batch_size)
        else:
            latent_image = _resize_image(image1, width, height)
            latent = {"samples": vae.encode(latent_image), "noise_mask": mask}
            if batch_size > 1 or latent["samples"].shape[0] != batch_size:
                latent = _repeat_latent_to_batch(latent, batch_size)

        if batch_size > 1:
            positive = positive * batch_size
            negative = negative * batch_size

        return (positive, negative, latent)
