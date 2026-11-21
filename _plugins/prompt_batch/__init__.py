"""TXT prompt-series loader and matching image saver."""

from __future__ import annotations

from .nodes import (
    LXPromptBatchLoader,
    LXPromptBatchSaveImage,
    register_prompt_batch_routes,
)
from .preview_bridge import install_prompt_progress_preview_bridge


install_prompt_progress_preview_bridge()
register_prompt_batch_routes()


NODE_CLASS_MAPPINGS = {
    "LXPromptBatch": LXPromptBatchLoader,
    "LXPromptBatchSaveImage": LXPromptBatchSaveImage,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "LXPromptBatch": "加载提示词（TXT系列）",
    "LXPromptBatchSaveImage": "保存图像（TXT系列）",
}

__all__ = [
    "NODE_CLASS_MAPPINGS",
    "NODE_DISPLAY_NAME_MAPPINGS",
]
