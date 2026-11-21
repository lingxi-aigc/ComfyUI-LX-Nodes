"""Offline translation nodes for LX-Nodes."""

from .offline_translator import LXOfflineTranslator

NODE_CLASS_MAPPINGS = {
    "LXOfflineTranslator": LXOfflineTranslator,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "LXOfflineTranslator": "离线翻译",
}

__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS"]
