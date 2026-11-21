# -*- coding: utf-8 -*-
"""
图片压缩节点
"""

from .nodes import ImageCompression, LXImageMultiResizeBySide, LXImageResizeBySide, SaveJPGImage

# 注册节点
NODE_CLASS_MAPPINGS = {
    "LXImageCompression": ImageCompression,
    "LXImageMultiResizeBySide": LXImageMultiResizeBySide,
    "LXImageResizeBySide": LXImageResizeBySide,
    "LXSaveJPGImage": SaveJPGImage,
}

# 节点显示名称
NODE_DISPLAY_NAME_MAPPINGS = {
    "LXImageCompression": "图像高质压缩",
    "LXImageMultiResizeBySide": "图像批量缩放（按边）",
    "LXImageResizeBySide": "图像缩放（按边）",
    "LXSaveJPGImage": "保存图像（JPG）",
}

# 导出必要的变量
__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS"]
