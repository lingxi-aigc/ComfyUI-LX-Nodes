from __future__ import annotations

import re

from ..categories import LX_TEXT_CATEGORY


_LINE_BREAK_PATTERN = re.compile(r"\r\n?|\n")


def string_to_list(value: object) -> list[str]:
    """Convert non-empty text lines to string-list items."""
    text = "" if value is None else str(value)
    return [
        item
        for part in _LINE_BREAK_PATTERN.split(text)
        if (item := part.strip())
    ]


class LXStringToList:
    """Convert non-empty text lines to a ComfyUI string list."""

    CATEGORY = LX_TEXT_CATEGORY
    SEARCH_ALIASES = [
        "lx",
        "LX",
        "灵犀",
        "字符串转列表",
        "文本转列表",
        "去除空格",
        "string to list",
    ]
    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("列表",)
    OUTPUT_IS_LIST = (True,)
    FUNCTION = "convert"

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "字符串": ("STRING", {"forceInput": True}),
            },
        }

    def convert(self, 字符串: str = ""):
        return (string_to_list(字符串),)
