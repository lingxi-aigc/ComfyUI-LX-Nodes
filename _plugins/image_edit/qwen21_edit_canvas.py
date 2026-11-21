"""Plan a Qwen Image 2.1 target canvas independently of its references."""

import torch
import torch.nn.functional as F
from comfy.latent_formats import QwenImage21
from comfy.model_management import intermediate_device
from comfy_api.latest import io

from ..categories import LX_IMAGE_EDIT_CATEGORY


TARGET_STRIDE = QwenImage21.spacial_downscale_ratio
ALIGNMENT = 2 * TARGET_STRIDE


def _aligned_size(width, height, long_edge, alignment=ALIGNMENT):
    edge = max(alignment, long_edge // alignment * alignment)
    scale = edge / max(width, height)
    return tuple(max(alignment, round(side * scale / alignment) * alignment) for side in (width, height))


def _prepare_reference(image, max_edge):
    original_h, original_w = map(int, image.shape[1:3])
    ref_edge = min(max(original_w, original_h), max_edge)
    width, height = _aligned_size(original_w, original_h, ref_edge)
    if (width, height) == (original_w, original_h):
        return image, width, height
    resized = F.interpolate(
        image.movedim(-1, 1), size=(height, width), mode="bicubic",
        align_corners=False, antialias=True,
    ).clamp_(0, 1).movedim(1, -1)
    return resized, width, height


def _empty_target(width, height):
    return {"samples": torch.zeros(
        (1, QwenImage21.latent_channels, height // TARGET_STRIDE, width // TARGET_STRIDE),
        device=intermediate_device(),
    )}


class LXQwen21EditCanvas(io.ComfyNode):
    SEARCH_ALIASES = ["lx", "LX", "灵犀", "换动作", "高分辨率采样", "目标画布", "Qwen 2.1 pose canvas"]

    @classmethod
    def define_schema(cls):
        return io.Schema(
            node_id="LXQwen21EditCanvas",
            display_name="Qwen 2.1 高分辨率编辑画布",
            category=f"{LX_IMAGE_EDIT_CATEGORY}/Qwen",
            is_deprecated=True,
            search_aliases=cls.SEARCH_ALIASES,
            description="兼容旧工作流中的独立尺寸、人物参考和 Latent 接线。新建工作流可使用「Qwen 2.1 多图编辑画布」。",
            inputs=[
                io.Image.Input("appearance_image", display_name="图 1 · 人物服装"),
                io.Int.Input("sample_long_edge", display_name="采样长边", default=4096, min=256, max=8192, step=32),
                io.Int.Input(
                    "appearance_max_edge", display_name="人物参考长边上限", default=0, min=0, max=8192, step=32,
                    tooltip="0 随采样长边。人物参考按自己的原比例缩放，小图只做网格对齐。",
                ),
                io.Image.Input(
                    "frame_image", display_name="图 2 · 画幅参考", optional=True,
                    tooltip="接原始姿势图来决定出图比例。留空时按人物服装图的比例采样。",
                ),
            ],
            outputs=[
                io.Image.Output(display_name="对齐人物参考"),
                io.Latent.Output(display_name="目标 Latent"),
                io.Int.Output(display_name="采样宽"),
                io.Int.Output(display_name="采样高"),
                io.String.Output(display_name="尺寸说明"),
            ],
        )

    @classmethod
    def execute(cls, appearance_image, sample_long_edge, appearance_max_edge=0, frame_image=None):
        original_h, original_w = map(int, appearance_image.shape[1:3])
        frame = appearance_image if frame_image is None else frame_image
        frame_h, frame_w = map(int, frame.shape[1:3])
        sample_w, sample_h = _aligned_size(frame_w, frame_h, sample_long_edge)

        prepared, ref_w, ref_h = _prepare_reference(appearance_image, appearance_max_edge or sample_long_edge)

        frame_source = "图 1 · 人物服装" if frame_image is None else "图 2 · 画幅参考"
        note = (
            f"原生采样 {sample_w} × {sample_h}\n"
            f"画幅来源 {frame_source}  {frame_w} × {frame_h}\n"
            f"人物参考 {original_w} × {original_h} → {ref_w} × {ref_h}"
        )
        return io.NodeOutput(prepared, _empty_target(sample_w, sample_h), sample_w, sample_h, note)
