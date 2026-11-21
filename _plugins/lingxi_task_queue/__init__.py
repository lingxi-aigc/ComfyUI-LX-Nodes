# -*- coding: utf-8 -*-
"""Task queue style Lingxi image generation nodes."""

from .executor import LingxiBatchExecute
from .result_split import LingxiResultSplit
from .task import LingxiImageTask


NODE_CLASS_MAPPINGS = {
    "LingxiImageTask": LingxiImageTask,
    "LingxiBatchExecute": LingxiBatchExecute,
    "LingxiResultSplit": LingxiResultSplit,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "LingxiImageTask": "灵犀生图任务",
    "LingxiBatchExecute": "灵犀批量执行",
    "LingxiResultSplit": "灵犀结果拆分",
}

__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS"]
