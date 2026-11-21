# -*- coding: utf-8 -*-
from __future__ import annotations

try:
    from ..categories import LX_UTILITY_CATEGORY
except Exception:
    LX_UTILITY_CATEGORY = "灵犀/实用工具"


class AnyType(str):
    def __ne__(self, value: object) -> bool:
        return False


ANY = AnyType("*")


class _SetGetBase:
    CATEGORY = LX_UTILITY_CATEGORY
    DESCRIPTION = "前端虚拟节点，用于隐藏长连线，并可随时还原为真实连线。"
    SEARCH_ALIASES = [
        "lx",
        "LX",
        "lingxi",
        "灵犀",
        "set",
        "get",
        "set node",
        "get node",
        "setnode",
        "getnode",
        "设置点",
        "获取点",
    ]
    FUNCTION = "noop"

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {}}

    def noop(self):
        return ()


class LingxiSetPoint(_SetGetBase):
    RETURN_TYPES = (ANY,)
    RETURN_NAMES = ("输出",)

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "输入": (ANY, {"forceInput": True}),
            },
        }

    def noop(self, 输入=None):
        return (输入,)


class LingxiGetPoint(_SetGetBase):
    RETURN_TYPES = (ANY,)
    RETURN_NAMES = ("输出",)

    def noop(self):
        return (None,)


NODE_CLASS_MAPPINGS = {
    "LingxiSetPoint": LingxiSetPoint,
    "LingxiGetPoint": LingxiGetPoint,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "LingxiSetPoint": "设置点",
    "LingxiGetPoint": "获取点",
}
