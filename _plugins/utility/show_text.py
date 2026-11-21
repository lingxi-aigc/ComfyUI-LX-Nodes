from __future__ import annotations

from ..categories import LX_UTILITY_CATEGORY


class LXShowText:
    """Display incoming text and pass it through unchanged."""

    CATEGORY = LX_UTILITY_CATEGORY
    SEARCH_ALIASES = ["lx", "LX", "灵犀", "展示文本", "显示文本", "show text"]
    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("字符串",)
    FUNCTION = "show"
    OUTPUT_NODE = True

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "text": ("STRING", {"forceInput": True}),
            },
        }

    def show(self, text=""):
        text = "" if text is None else str(text)
        return {
            "ui": {"text": [text]},
            "result": (text,),
        }
