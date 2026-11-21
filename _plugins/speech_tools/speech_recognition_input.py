from __future__ import annotations

from ..categories import LX_ROOT_CATEGORY


class SpeechRecognitionInput:
    """Editable text source backed by local SenseVoice speech recognition."""

    CATEGORY = f"{LX_ROOT_CATEGORY}/语音工具"
    SEARCH_ALIASES = ["lx", "LX", "灵犀", "语音识别输入", "语音输入", "speech recognition"]
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
