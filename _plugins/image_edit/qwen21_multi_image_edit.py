"""Prepare Qwen Image 2.1 multi-image conditions and an independent target canvas."""

from comfy_api.latest import io, ui

from ..categories import LX_IMAGE_EDIT_CATEGORY
from .qwen21_edit_canvas import TARGET_STRIDE, _aligned_size, _empty_target, _prepare_reference


CUSTOM_RATIO = "自定义比例"
CUSTOM_SIZE = "自定义宽高"
MAX_REFERENCES = 10
REFERENCE_MODES = tuple(f"参考图 {index} 的画幅" for index in range(1, MAX_REFERENCES + 1))
RATIO_PRESETS = (
    "1:1", "16:9", "9:16", "4:3", "3:4", "3:2", "2:3", "4:5", "5:4",
    "2:1", "1:2", "5:3", "3:5", "21:9", "9:21", "3:1", "1:3", "32:9", "9:32",
)


def _long_edge():
    return io.Int.Input(
        "long_edge", display_name="采样分辨率", default=3360, min=256, max=8192, step=16,
        tooltip="采样长边的像素数。横图按宽，竖图按高，另一边按所选比例计算。",
    )


def _canvas_size(canvas, references):
    mode = canvas["canvas"]
    if mode == CUSTOM_SIZE:
        width, height = canvas["width"], canvas["height"]
        sample_w = width // TARGET_STRIDE * TARGET_STRIDE
        sample_h = height // TARGET_STRIDE * TARGET_STRIDE
        source = None if (sample_w, sample_h) == (width, height) else f"输入 {width} × {height}，已按 16 像素对齐"
        return sample_w, sample_h, source
    if mode == CUSTOM_RATIO:
        width, height = map(int, canvas["preset_ratio"].split(":"))
        source = f"自定义比例 {width}:{height}"
    else:
        index = REFERENCE_MODES.index(mode)
        if index >= len(references):
            raise ValueError(f"请连接参考图 {index + 1}，或在「出图尺寸」中选择其他设置。")
        height, width = map(int, references[index].shape[1:3])
        source = mode
    sample_w, sample_h = _aligned_size(width, height, canvas["long_edge"], TARGET_STRIDE)
    return sample_w, sample_h, source


class LXQwen21MultiImageEdit(io.ComfyNode):
    SEARCH_ALIASES = ["lx", "LX", "灵犀", "Qwen 2.1 姿势迁移", "换动作", "多图编辑", "高分辨率采样"]

    @classmethod
    def define_schema(cls):
        return io.Schema(
            node_id="LXQwen21MultiImageEdit",
            display_name="Qwen 2.1 多图编辑画布",
            category=f"{LX_IMAGE_EDIT_CATEGORY}/Qwen",
            search_aliases=cls.SEARCH_ALIASES,
            description="给 Qwen 2.1 指定参考图和实际采样尺寸。提示词可用 <image1>、<image2> 引用参考图。",
            inputs=[
                io.Clip.Input("clip", display_name="Qwen 2.1 CLIP"),
                io.Vae.Input("vae", display_name="Qwen 2.1 VAE"),
                io.Autogrow.Input(
                    "images",
                    template=io.Autogrow.TemplateNames(
                        io.Image.Input("image"),
                        names=[f"image_{i}" for i in range(1, MAX_REFERENCES + 1)],
                        min=1,
                    ),
                    tooltip="参考图按接线插槽的顺序编号。换动作时，图 1 接人物照，图 2 接姿势图。",
                ),
                io.String.Input(
                    "prompt", display_name="正向提示词", placeholder="正向提示词 · 输入想修改的内容",
                    multiline=True, dynamic_prompts=True,
                ),
                io.DynamicCombo.Input(
                    "canvas", display_name="出图尺寸",
                    options=[
                        *(io.DynamicCombo.Option(mode, [_long_edge()]) for mode in REFERENCE_MODES),
                        io.DynamicCombo.Option(CUSTOM_RATIO, [
                            io.Combo.Input("preset_ratio", display_name="宽高比", options=list(RATIO_PRESETS), default="16:9"),
                            _long_edge(),
                        ]),
                        io.DynamicCombo.Option(CUSTOM_SIZE, [
                            io.Int.Input("width", display_name="出图宽度（像素）", default=4096, min=16, max=8192, step=16),
                            io.Int.Input("height", display_name="出图高度（像素）", default=2304, min=16, max=8192, step=16),
                        ]),
                    ],
                    tooltip="选择已接入参考图的画幅，也可以指定宽高比或尺寸。",
                ),
                io.Int.Input(
                    "appearance_max_edge", display_name="图 1 参考长边上限", default=2048, min=256, max=8192, step=32,
                    tooltip="图 1 太大时先等比缩小再送进模型。这个值只控制参考图。",
                ),
                io.Int.Input(
                    "reference_max_edge", display_name="其他参考图长边上限", default=1536,
                    min=256, max=8192, step=32, advanced=True,
                    tooltip="图 2 起，每张参考图单独按这个上限缩小。",
                ),
                io.String.Input(
                    "negative_prompt", display_name="负向提示词", default="", multiline=True,
                    placeholder="负向提示词", dynamic_prompts=True, optional=True,
                ),
            ],
            outputs=[
                io.Conditioning.Output(display_name="正面条件"),
                io.Conditioning.Output(display_name="负面条件"),
                io.Latent.Output(display_name="Latent"),
                io.String.Output(display_name="采样与参考尺寸"),
            ],
        )

    @classmethod
    def execute(cls, clip, vae, images, prompt, canvas, appearance_max_edge=2048,
                reference_max_edge=1536, negative_prompt=""):
        from comfy_extras.nodes_qwen import TextEncodeQwenImage21

        references = [images[name] for name in sorted(images, key=lambda name: int(name.rsplit("_", 1)[-1]))
                      if images[name] is not None]
        if not references:
            raise ValueError("请至少连接一张参考图。")
        width, height, source = _canvas_size(canvas, references)
        prepared = {}
        sizes = []
        for index, image in enumerate(references, start=1):
            cap = appearance_max_edge if index == 1 else reference_max_edge
            reference, ref_w, ref_h = _prepare_reference(image, cap)
            prepared[f"image_{index}"] = reference
            sizes.append(f"图 {index}  {ref_w} × {ref_h}")
        positive, negative, _ = TextEncodeQwenImage21.execute(
            clip, prompt, negative_prompt, vae=vae, resolution=0, images=prepared,
        ).result
        report_lines = [f"实际采样  {width} × {height} 像素（宽 × 高）"]
        if source:
            report_lines.append(f"出图设置  {source}")
        report = "\n".join([*report_lines, "送进模型的参考图（像素）", *sizes])
        return io.NodeOutput(positive, negative, _empty_target(width, height), report, ui=ui.PreviewText(report))
