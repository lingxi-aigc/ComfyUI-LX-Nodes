"""Prompt helper nodes for LX-Nodes."""

from .lx_prompt_splitter import LXPromptSplitter

NODE_CLASS_MAPPINGS = {
    "LXPromptSplitter": LXPromptSplitter,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "LXPromptSplitter": "提示词分段",
}

__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS"]
