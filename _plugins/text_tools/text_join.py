from __future__ import annotations

from ..categories import LX_TEXT_CATEGORY


class LXTextJoin:
    """Join up to four text inputs with a custom delimiter."""

    CATEGORY = LX_TEXT_CATEGORY
    SEARCH_ALIASES = ["lx", "LX", "灵犀", "文本连锁", "文本拼接", "文本合并", "text join"]
    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("文本",)
    FUNCTION = "join_text"

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "连接符": (
                    "STRING",
                    {
                        "default": ",",
                        "multiline": False,
                    },
                ),
            },
            "optional": {
                "文本1": ("STRING", {"forceInput": True}),
                "文本2": ("STRING", {"forceInput": True}),
                "文本3": ("STRING", {"forceInput": True}),
                "文本4": ("STRING", {"forceInput": True}),
            },
        }

    def join_text(
        self,
        连接符: str = ",",
        文本1: str | None = None,
        文本2: str | None = None,
        文本3: str | None = None,
        文本4: str | None = None,
    ):
        delimiter = "," if 连接符 is None else str(连接符)
        parts = []
        for item in (文本1, 文本2, 文本3, 文本4):
            text = "" if item is None else str(item)
            if text:
                parts.append(text)
        return (delimiter.join(parts),)
