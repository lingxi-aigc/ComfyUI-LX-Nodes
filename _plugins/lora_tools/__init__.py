# -*- coding: utf-8 -*-
from __future__ import annotations

from .multi_lora_loader import MultiLoraLoader


NODE_CLASS_MAPPINGS = {
    "MultiLoraLoader": MultiLoraLoader,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "MultiLoraLoader": "LoRA加载器（多重）",
}

__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS"]
