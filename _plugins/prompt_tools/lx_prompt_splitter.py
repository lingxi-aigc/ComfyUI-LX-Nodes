from __future__ import annotations

from ..categories import LX_TEXT_CATEGORY


MAX_DYNAMIC_PROMPT_OUTPUTS = 32
DEFAULT_PROMPT_OUTPUTS = 8


def _clamp_count(value: int | str | float | None) -> int:
    try:
        count = int(value)
    except (TypeError, ValueError):
        count = DEFAULT_PROMPT_OUTPUTS
    return max(1, min(MAX_DYNAMIC_PROMPT_OUTPUTS, count))


class LXPromptSplitter:
    """Split pasted prompt text into the active dynamic output slots."""

    CATEGORY = LX_TEXT_CATEGORY
    SEARCH_ALIASES = ["lx", "LX", "灵犀", "提示词分段", "提示词拆分", "prompt splitter"]
    RETURN_TYPES = ("STRING",) * MAX_DYNAMIC_PROMPT_OUTPUTS
    RETURN_NAMES = tuple(f"prompt{i}" for i in range(1, MAX_DYNAMIC_PROMPT_OUTPUTS + 1))
    FUNCTION = "split_prompts"

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "文本": (
                    "STRING",
                    {
                        "forceInput": True,
                    },
                ),
                "数量": (
                    "INT",
                    {
                        "default": DEFAULT_PROMPT_OUTPUTS,
                        "min": 1,
                        "max": MAX_DYNAMIC_PROMPT_OUTPUTS,
                        "step": 1,
                    },
                ),
                "添加前缀": (
                    "STRING",
                    {
                        "multiline": False,
                        "default": "",
                    },
                ),
                "添加后缀": (
                    "STRING",
                    {
                        "multiline": False,
                        "default": "",
                    },
                ),
            }
        }

    def split_prompts(self, 文本="", 数量=DEFAULT_PROMPT_OUTPUTS, 添加前缀="", 添加后缀=""):
        output_count = _clamp_count(数量)
        prefix = "" if 添加前缀 is None else str(添加前缀)
        suffix = "" if 添加后缀 is None else str(添加后缀)

        lines = []
        for line in str(文本 or "").splitlines():
            prompt = line.strip()
            if prompt:
                lines.append(prompt)

        outputs = []
        for index in range(output_count):
            if index < len(lines):
                outputs.append(f"{prefix}{lines[index]}{suffix}")
            else:
                outputs.append("")
        return tuple(outputs)


NODE_CLASS_MAPPINGS = {"LXPromptSplitter": LXPromptSplitter}
NODE_DISPLAY_NAME_MAPPINGS = {"LXPromptSplitter": "提示词分段"}
