# -*- coding: utf-8 -*-
"""Concurrent Lingxi Bridge nodes."""

from .api_pool import LingxiBridgeApiPool
from .api_pool_merge import LingxiBridgeApiPoolMerge
from .concurrent_image import LingxiBridgeConcurrentImage

NODE_CLASS_MAPPINGS = {
    "LingxiBridgeApiPool": LingxiBridgeApiPool,
    "LingxiBridgeApiPoolMerge": LingxiBridgeApiPoolMerge,
    "LingxiBridgeConcurrentImage": LingxiBridgeConcurrentImage,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "LingxiBridgeApiPool": "灵犀API池",
    "LingxiBridgeApiPoolMerge": "API池合并",
    "LingxiBridgeConcurrentImage": "灵犀批量生图（旧版）",
}

__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS"]
