# -*- coding: utf-8 -*-
"""
LX_图像对比子插件入口。
"""

from .image_compare import LXImageCompare

NODE_CLASS_MAPPINGS = {
    "LXImageCompare": LXImageCompare,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "LXImageCompare": "图像对比",
}

__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS"]
