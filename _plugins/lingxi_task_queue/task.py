# -*- coding: utf-8 -*-
from __future__ import annotations

from typing import Any

from ..categories import LX_RELAY_CATEGORY
from ..lingxi_bridge.lb_image import (
    GPT_IMAGE2_MODERATIONS,
    GPT_IMAGE2_QUALITIES,
    IMAGE_RATIOS,
    IMAGE_SIZES,
)
from .shared import MAX_TASK_IMAGES, TASKS_TYPE, clean_str, normalize_tasks, task_payload


class LingxiImageTask:
    CATEGORY = f"{LX_RELAY_CATEGORY}/任务批量"
    RETURN_TYPES = (TASKS_TYPE,)
    RETURN_NAMES = ("tasks",)
    FUNCTION = "build_task"
    SIZE = (460, 520)
    SEARCH_ALIASES = ("lx", "LX", "灵犀", "灵犀生图任务", "任务", "批量任务", "生图任务")

    @classmethod
    def INPUT_TYPES(cls):
        optional: dict[str, Any] = {
            "tasks_in": (TASKS_TYPE,),
            "本任务API": ("STRING", {"default": "", "forceInput": True}),
        }
        for index in range(1, MAX_TASK_IMAGES + 1):
            optional[f"image{index}"] = ("IMAGE",)

        return {
            "required": {
                "prompt": ("STRING", {"default": "", "multiline": True}),
                "ratio": (IMAGE_RATIOS, {"default": "auto"}),
                "size": (IMAGE_SIZES, {"default": "2K"}),
                "quality": (GPT_IMAGE2_QUALITIES, {"default": "medium"}),
                "moderation": (GPT_IMAGE2_MODERATIONS, {"default": "low"}),
                "重新生成": ("BOOLEAN", {"default": False}),
            },
            "optional": optional,
            "hidden": {
                "unique_id": "UNIQUE_ID",
            },
        }

    @classmethod
    def VALIDATE_INPUTS(cls, **kwargs):
        return True

    def build_task(
        self,
        prompt="",
        ratio="auto",
        size="2K",
        quality="medium",
        moderation="low",
        重新生成=False,
        unique_id=None,
        **kwargs,
    ):
        tasks = normalize_tasks(kwargs.get("tasks_in"))
        images = [
            kwargs[f"image{index}"]
            for index in range(1, MAX_TASK_IMAGES + 1)
            if kwargs.get(f"image{index}") is not None
        ]
        task_index = len(tasks) + 1
        task = {
            "type": "lx_image_task",
            "version": 1,
            "task_id": clean_str(unique_id) or f"task_{task_index}",
            "index": task_index,
            "name": f"任务{task_index}",
            "enabled": True,
            "prompt": clean_str(prompt),
            "images": images,
            "ratio": clean_str(ratio) or "auto",
            "size": clean_str(size) or "2K",
            "quality": clean_str(quality) or "medium",
            "moderation": clean_str(moderation) or "low",
            "regenerate": bool(重新生成),
            "api": clean_str(kwargs.get("本任务API", "")),
        }
        tasks.append(task)
        return (task_payload(tasks),)
