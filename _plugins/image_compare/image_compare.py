# -*- coding: utf-8 -*-
"""
LX_图像对比节点

继承 ComfyUI 内置 PreviewImage，调用 save_images 把两组张量图片保存到 temp，
返回 a_images / b_images 供前端渲染 Slide/Click 对比。
"""

from nodes import PreviewImage

from ..categories import LX_IMAGE_CATEGORY


class LXImageCompare(PreviewImage):
    """Compare two image batches with a hover-slide or click-to-toggle UI."""

    CATEGORY = LX_IMAGE_CATEGORY
    ESSENTIALS_CATEGORY = ""
    SEARCH_ALIASES = ["lx", "LX", "灵犀", "图像对比", "LX 图像对比", "灵犀 图像对比", "image compare"]
    FUNCTION = "compare_images"
    OUTPUT_NODE = True
    RETURN_TYPES = ()
    RETURN_NAMES = ()
    OUTPUT_IS_LIST = ()

    DESCRIPTION = (
        "对比两组 IMAGE：鼠标在节点上滑动可拖动分界线；"
        "右键 → Properties → comparer_mode 可切换 Slide（滑动）和 Click（按住切换）。"
        "多图批次会显示 A1/A2/B1/B2 等标签，点击即可选择参与对比的那一张。"
    )

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {},
            "optional": {
                "图像A": ("IMAGE",),
                "图像B": ("IMAGE",),
            },
            "hidden": {
                "prompt": "PROMPT",
                "extra_pnginfo": "EXTRA_PNGINFO",
            },
        }

    def compare_images(
        self,
        图像A=None,
        图像B=None,
        filename_prefix="lx.compare.",
        prompt=None,
        extra_pnginfo=None,
    ):
        result = {"ui": {"a_images": [], "b_images": []}}

        if 图像A is not None and len(图像A) > 0:
            result["ui"]["a_images"] = self.save_images(
                图像A, filename_prefix, prompt, extra_pnginfo
            )["ui"]["images"]

        if 图像B is not None and len(图像B) > 0:
            result["ui"]["b_images"] = self.save_images(
                图像B, filename_prefix, prompt, extra_pnginfo
            )["ui"]["images"]

        return result
