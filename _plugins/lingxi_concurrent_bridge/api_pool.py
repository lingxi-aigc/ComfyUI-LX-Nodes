# -*- coding: utf-8 -*-
from __future__ import annotations

import json

from ..categories import LX_RELAY_CATEGORY
from ..lingxi_bridge.lb_config import (
    IMAGE_API_FORMATS,
    PLATFORMS,
    get_api_base_list,
    get_catalog_for_base,
)


def _normalize_api_key(value: object) -> str:
    key = "" if value is None else str(value).strip()
    if not key or key.lower() in {"none", "null"}:
        return ""
    return key


def _clean_api_key_entries(value: object, origin: str) -> list[dict[str, str]]:
    text = "" if value is None else str(value)
    entries: list[dict[str, str]] = []
    lines = text.splitlines() or [text]
    for line_index, line in enumerate(lines, start=1):
        key = _normalize_api_key(line)
        if key:
            label = origin if len(lines) == 1 else f"{origin} 第{line_index}行"
            entries.append({"api_key": key, "origin_label": label})
    return entries


def _clean_batch_api_key_entries(value: object) -> list[dict[str, str]]:
    text = "" if value is None else str(value)
    entries: list[dict[str, str]] = []
    for line_index, line in enumerate(text.splitlines(), start=1):
        raw = line.strip()
        if not raw or raw.startswith("#"):
            continue
        key = _normalize_api_key(raw.split("#", 1)[0])
        if key:
            entries.append({"api_key": key, "origin_label": f"keys_text 第{line_index}行"})
    return entries


def _resolve_api_key_entries(values: list[tuple[str, object]], batch_value: object = "") -> list[dict[str, str | int]]:
    entries: list[dict[str, str | int]] = []
    seen: set[str] = set()
    for origin, value in values:
        for entry in _clean_api_key_entries(value, origin):
            key = str(entry["api_key"])
            if key in seen:
                continue
            seen.add(key)
            entries.append(entry)
    for entry in _clean_batch_api_key_entries(batch_value):
        key = str(entry["api_key"])
        if key in seen:
            continue
        seen.add(key)
        entries.append(entry)
    for index, entry in enumerate(entries, start=1):
        entry["api_index"] = index
    return entries


class LingxiBridgeApiPool:
    CATEGORY = f"{LX_RELAY_CATEGORY}/接口配置"
    SEARCH_ALIASES = ("lx", "LX", "灵犀", "灵犀API池", "API池", "api pool")
    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("api_pool",)
    FUNCTION = "build_pool"
    SIZE = (420, 360)

    @classmethod
    def INPUT_TYPES(cls):
        api_base_list = get_api_base_list()
        default_base = api_base_list[0] if api_base_list else ""
        catalog = get_catalog_for_base(default_base) if default_base else {}
        api_format_list = list(catalog.keys()) or IMAGE_API_FORMATS
        default_api_format = api_format_list[0] if api_format_list else ""
        model_list = catalog.get(default_api_format, [""]) or [""]

        return {
            "required": {
                "platform": (PLATFORMS, {"default": PLATFORMS[0]}),
                "api_base": (api_base_list, {"default": default_base}),
                "api_format": (api_format_list, {"default": default_api_format}),
                "model": (model_list, {"default": model_list[0] if model_list else ""}),
                "apikey1": ("STRING", {"default": ""}),
                "apikey2": ("STRING", {"default": ""}),
                "apikey3": ("STRING", {"default": ""}),
                "apikey4": ("STRING", {"default": ""}),
            },
            "optional": {
                "keys_text": (
                    "STRING",
                    {
                        "default": "",
                        "forceInput": True,
                        "tooltip": "Connect a text node: one API key per line, use # for notes.",
                    },
                ),
                "custom_api_base": (
                    "STRING",
                    {
                        "default": "",
                        "placeholder": "填写后覆盖上方 api_base",
                    },
                ),
                "custom_api_format": (
                    "STRING",
                    {
                        "default": "",
                        "placeholder": "填写后覆盖上方 api_format",
                    },
                ),
                "custom_model": (
                    "STRING",
                    {
                        "default": "",
                        "placeholder": "填写后覆盖上方 model",
                    },
                ),
            },
            "hidden": {
                "unique_id": "UNIQUE_ID",
            },
        }

    @classmethod
    def VALIDATE_INPUTS(cls, **kwargs):
        return True

    def build_pool(
        self,
        platform,
        api_base,
        api_format,
        model,
        apikey1="",
        apikey2="",
        apikey3="",
        apikey4="",
        custom_api_base="",
        custom_api_format="",
        custom_model="",
        unique_id=None,
        **kwargs,
    ):
        effective_base = (custom_api_base.strip().rstrip("/") if custom_api_base else "") or api_base
        effective_format = (custom_api_format.strip() if custom_api_format else "") or api_format
        effective_model = (custom_model.strip() if custom_model else "") or model
        key_entries = _resolve_api_key_entries(
            [
                ("apikey1", apikey1),
                ("apikey2", apikey2),
                ("apikey3", apikey3),
                ("apikey4", apikey4),
            ],
            kwargs.get("keys_text", ""),
        )
        channels = [
            {
                "source": "api_pool",
                "api_index": entry["api_index"],
                "origin_label": entry["origin_label"],
                "platform": platform,
                "api_base": (effective_base or "").strip().rstrip("/"),
                "api_format": effective_format or "",
                "model": effective_model or "",
                "api_key": entry["api_key"],
            }
            for entry in key_entries
        ]

        payload = {
            "type": "lingxi_api_pool",
            "version": 3,
            "channels": channels,
        }
        print(
            "[LingxiBridgeApiPool] "
            f"{platform} | {effective_format or ''} | {(effective_base or '').strip().rstrip('/')} | "
            f"{effective_model or ''} | keys={len(channels)}"
        )
        return (json.dumps(payload, ensure_ascii=False),)
