"""Text utility nodes for LX-Nodes."""

from .text import LXText
from .text_join import LXTextJoin
from .text_replace import LXTextReplace
from .prompt_list import LXPromptList
from .string_to_list import LXStringToList

NODE_CLASS_MAPPINGS = {
    "LXText": LXText,
    "LXTextJoin": LXTextJoin,
    "LXTextReplace": LXTextReplace,
    "LXPromptList": LXPromptList,
    "LXStringToList": LXStringToList,
}
NODE_DISPLAY_NAME_MAPPINGS = {
    "LXText": "文本",
    "LXTextJoin": "文本连锁",
    "LXTextReplace": "文本替换",
    "LXPromptList": "提示词列表",
    "LXStringToList": "字符串转列表",
}

__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS"]
