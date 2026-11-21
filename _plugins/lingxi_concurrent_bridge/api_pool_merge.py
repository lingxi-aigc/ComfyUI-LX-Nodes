# -*- coding: utf-8 -*-
from __future__ import annotations

import json
from typing import Any

from ..categories import LX_RELAY_CATEGORY


MAX_INFO_INPUTS = 8
def _clean(value: object) -> str:
    return "" if value is None else str(value).strip()


def _safe_json(value: object) -> dict[str, Any]:
    if not isinstance(value, str) or not value.strip():
        return {}
    try:
        data = json.loads(value)
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _channel_from_info(value: object, source: str, api_index: int) -> dict[str, Any] | None:
    data = _safe_json(value)
    if not data:
        return None

    api_key = _clean(data.get("apikey") or data.get("api_key"))
    channel = {
        "source": source,
        "api_index": api_index,
        "origin_label": source,
        "platform": _clean(data.get("platform") or "banana-pro"),
        "api_base": _clean(data.get("api_base")).rstrip("/"),
        "api_format": _clean(data.get("api_format") or "v1/images"),
        "model": _clean(data.get("model")),
        "api_key": api_key,
    }
    if not any(channel.get(k) for k in ("api_base", "api_format", "model", "api_key")):
        return None
    return channel


class LingxiBridgeApiPoolMerge:
    CATEGORY = f"{LX_RELAY_CATEGORY}/接口配置"
    SEARCH_ALIASES = ("lx", "LX", "灵犀", "灵犀API池合并", "API池合并", "api pool merge")
    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("api_pool",)
    FUNCTION = "merge"
    SIZE = (360, 360)

    @classmethod
    def INPUT_TYPES(cls):
        optional: dict[str, Any] = {}
        for index in range(1, MAX_INFO_INPUTS + 1):
            optional[f"info{index}"] = ("STRING", {"default": "", "forceInput": True})
        return {"optional": optional}

    @classmethod
    def VALIDATE_INPUTS(cls, **kwargs):
        return True

    def merge(self, **kwargs):
        channels: list[dict[str, Any]] = []

        for index in range(1, MAX_INFO_INPUTS + 1):
            channel = _channel_from_info(kwargs.get(f"info{index}", ""), f"info{index}", len(channels) + 1)
            if channel:
                channels.append(channel)

        payload = {
            "type": "lingxi_api_pool",
            "version": 3,
            "channels": channels,
        }
        print(f"[LingxiBridgeApiPoolMerge] channels={len(channels)}")
        return (json.dumps(payload, ensure_ascii=False),)
