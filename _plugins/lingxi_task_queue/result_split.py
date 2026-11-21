# -*- coding: utf-8 -*-
from __future__ import annotations

from typing import Any

from PIL import Image

from ..categories import LX_RELAY_CATEGORY
from .shared import DEFAULT_SPLIT_COUNT, EMPTY_SIZE, MAX_TASKS, RESULTS_TYPE, blank_image, to_tensor


def _clamp_int(value: object, default: int, min_value: int, max_value: int) -> int:
    try:
        number = int(float(value))
    except (TypeError, ValueError):
        number = default
    return max(min_value, min(max_value, number))


def _result_items(results: object) -> list[dict[str, Any]]:
    if not isinstance(results, dict) or results.get("type") != "lx_image_results":
        return []
    items = results.get("items", [])
    return [item for item in items if isinstance(item, dict)] if isinstance(items, list) else []


class LingxiResultSplit:
    CATEGORY = f"{LX_RELAY_CATEGORY}/任务批量"
    RETURN_TYPES = ("IMAGE",) * MAX_TASKS
    RETURN_NAMES = tuple(f"image{index}" for index in range(1, MAX_TASKS + 1))
    FUNCTION = "split"
    SIZE = (320, 260)
    SEARCH_ALIASES = ("lx", "LX", "灵犀", "灵犀结果拆分", "结果拆分", "拆图", "批量拆分")

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "results": (RESULTS_TYPE,),
                "起始序号": ("INT", {"default": 1, "min": 1, "max": MAX_TASKS, "step": 1}),
                "拆分数量": ("INT", {"default": DEFAULT_SPLIT_COUNT, "min": 1, "max": MAX_TASKS, "step": 1}),
            }
        }

    @classmethod
    def VALIDATE_INPUTS(cls, **kwargs):
        return True

    def split(self, results, 起始序号=1, 拆分数量=DEFAULT_SPLIT_COUNT):
        start = _clamp_int(起始序号, 1, 1, MAX_TASKS) - 1
        count = _clamp_int(拆分数量, DEFAULT_SPLIT_COUNT, 1, MAX_TASKS)
        items = _result_items(results)
        outputs = []
        for offset in range(MAX_TASKS):
            source_index = start + offset
            image = None
            if offset < count and 0 <= source_index < len(items):
                candidate = items[source_index].get("image")
                if isinstance(candidate, Image.Image):
                    image = candidate.convert("RGB")
            if image is None:
                image = blank_image(EMPTY_SIZE)
            outputs.append(to_tensor(image))
        return tuple(outputs)
