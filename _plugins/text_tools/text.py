from __future__ import annotations

from ..categories import LX_TEXT_CATEGORY


class LXText:
    """Simple multiline text source."""

    CATEGORY = LX_TEXT_CATEGORY
    SEARCH_ALIASES = ["lx", "LX", "灵犀", "文本", "文本输入", "text"]
    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("文本",)
    FUNCTION = "emit"

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "文本": (
                    "STRING",
                    {
                        "default": "",
                        "multiline": True,
                    },
                ),
            },
        }

    def emit(self, 文本: str = ""):
        return ("" if 文本 is None else str(文本),)
