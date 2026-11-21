# -*- coding: utf-8 -*-
"""Folder-level batch API generation nodes."""

from .executor import LingxiFolderBatchExecuteSave
from .generator import LingxiMultiFolderBatchGenerate, LingxiSingleFolderBatchGenerate


NODE_CLASS_MAPPINGS = {
    "LingxiSingleFolderBatchGenerate": LingxiSingleFolderBatchGenerate,
    "LingxiMultiFolderBatchGenerate": LingxiMultiFolderBatchGenerate,
    "LingxiFolderBatchExecuteSave": LingxiFolderBatchExecuteSave,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "LingxiSingleFolderBatchGenerate": "灵犀单图批量（文件夹）",
    "LingxiMultiFolderBatchGenerate": "灵犀多图批量（文件夹）",
    "LingxiFolderBatchExecuteSave": "灵犀批量执行（文件夹）",
}

__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS"]
