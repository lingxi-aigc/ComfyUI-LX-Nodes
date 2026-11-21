# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import re
from typing import Any, Iterable

import folder_paths


class AnyType(str):
    def __ne__(self, value: object) -> bool:
        return False


ANY = AnyType("*")


class FlexibleOptionalInputType(dict):
    """Accept custom dynamic LoRA rows serialized by the frontend."""

    def __getitem__(self, key: str):
        return (ANY, {})

    def __contains__(self, key: object) -> bool:
        return True


def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return default


def _normalize_lora_item(value: Any) -> dict[str, Any] | None:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except Exception:
            return None
    if not isinstance(value, dict):
        return None

    lora_name = value.get("lora") or value.get("name") or value.get("lora_name")
    if not lora_name or lora_name == "None":
        return None

    return {
        "on": bool(value.get("on", value.get("enabled", True))),
        "lora": str(lora_name),
        "strength": _as_float(value.get("strength", value.get("strength_model", 1.0)), 1.0),
    }


def _item_index(name: str) -> int:
    match = re.match(r"^lora_(\d+)$", name)
    return int(match.group(1)) if match else 10_000


def _iter_lora_items(kwargs: dict[str, Any]) -> Iterable[dict[str, Any]]:
    loras = kwargs.get("loras")
    if isinstance(loras, str):
        try:
            loras = json.loads(loras)
        except Exception:
            loras = None

    if isinstance(loras, list):
        for value in loras:
            item = _normalize_lora_item(value)
            if item is not None:
                yield item

    for name in sorted((key for key in kwargs if _item_index(key) < 10_000), key=_item_index):
        item = _normalize_lora_item(kwargs.get(name))
        if item is not None:
            yield item


class MultiLoraLoader:
    """Apply multiple LoRAs to a model in order."""

    CATEGORY = "model/loaders"
    DESCRIPTION = "Load and stack multiple LoRAs onto a MODEL with per-LoRA enable switches and strengths."
    SEARCH_ALIASES = [
        "lx",
        "LX",
        "灵犀",
        "lora",
        "multi lora",
        "lora loader",
        "LoRA加载器",
        "LoRA加载器（多重）",
        "多重LoRA",
    ]
    RETURN_TYPES = ("MODEL",)
    RETURN_NAMES = ("MODEL",)
    FUNCTION = "load_loras"

    def __init__(self):
        self.loaded_loras: dict[str, tuple[dict[str, Any], dict[str, Any] | None]] = {}

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "model": ("MODEL", {"tooltip": "The diffusion model the LoRAs will be applied to."}),
            },
            "optional": FlexibleOptionalInputType(),
        }

    def _load_lora_file(self, lora_name: str):
        import comfy.utils

        lora_path = folder_paths.get_full_path_or_raise("loras", lora_name)
        cached = self.loaded_loras.get(lora_path)
        if cached is not None:
            return cached

        lora, lora_metadata = comfy.utils.load_torch_file(
            lora_path,
            safe_load=True,
            return_metadata=True,
        )
        self.loaded_loras[lora_path] = (lora, lora_metadata)
        return lora, lora_metadata

    def load_loras(self, model, **kwargs):
        import comfy.sd

        for item in _iter_lora_items(kwargs):
            if not item["on"]:
                continue

            strength = item["strength"]
            if strength == 0:
                continue

            lora, lora_metadata = self._load_lora_file(item["lora"])
            model, _ = comfy.sd.load_lora_for_models(
                model,
                None,
                lora,
                strength,
                0,
                lora_metadata=lora_metadata,
            )

        return (model,)
