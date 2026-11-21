from __future__ import annotations

from ..categories import LX_ROOT_CATEGORY


class SpeechRecognitionInputPlus:
    """Editable text source backed by streaming speech recognition."""

    CATEGORY = f"{LX_ROOT_CATEGORY}/语音工具"
    SEARCH_ALIASES = ["lx", "LX", "灵犀", "语音识别输入Plus", "语音输入Plus", "speech recognition plus"]
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

    def emit(self, **kwargs):
        text = kwargs.get("文本", kwargs.get("text", ""))
        return ("" if text is None else str(text),)
