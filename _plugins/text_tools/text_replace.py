from __future__ import annotations

from ..categories import LX_TEXT_CATEGORY


def _to_text(value: object) -> str:
    return "" if value is None else str(value)


class LXTextReplace:
    """Replace text with up to four ordered literal replacement pairs."""

    CATEGORY = LX_TEXT_CATEGORY
    SEARCH_ALIASES = ["lx", "LX", "灵犀", "文本替换", "替换文本", "find replace", "text replace"]
    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("文本",)
    FUNCTION = "replace_text"

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "文本": ("STRING", {"forceInput": True}),
                "查找1": ("STRING", {"default": "", "multiline": False}),
                "替换1": ("STRING", {"default": "", "multiline": False}),
                "查找2": ("STRING", {"default": "", "multiline": False}),
                "替换2": ("STRING", {"default": "", "multiline": False}),
                "查找3": ("STRING", {"default": "", "multiline": False}),
                "替换3": ("STRING", {"default": "", "multiline": False}),
                "查找4": ("STRING", {"default": "", "multiline": False}),
                "替换4": ("STRING", {"default": "", "multiline": False}),
            },
        }

    def replace_text(
        self,
        文本: str = "",
        查找1: str = "",
        替换1: str = "",
        查找2: str = "",
        替换2: str = "",
        查找3: str = "",
        替换3: str = "",
        查找4: str = "",
        替换4: str = "",
    ):
        result = _to_text(文本)
        for old, new in (
            (查找1, 替换1),
            (查找2, 替换2),
            (查找3, 替换3),
            (查找4, 替换4),
        ):
            old_text = _to_text(old)
            if old_text:
                result = result.replace(old_text, _to_text(new))
        return (result,)
