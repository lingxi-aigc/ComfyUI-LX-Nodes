"""Keep prompt progress previews out of ComfyUI's generated-assets history."""

from __future__ import annotations

from typing import Any, Dict


PROGRESS_UI_KEY = "lx_prompt_progress_preview"
PROGRESS_OUTPUT_INDEX = 5


def _is_prompt_progress_link(
    prompt: Any,
    unique_id: Any,
) -> bool:
    if not isinstance(prompt, dict) or unique_id is None:
        return False

    node_data = prompt.get(str(unique_id), prompt.get(unique_id))
    if not isinstance(node_data, dict):
        return False

    inputs = node_data.get("inputs")
    if not isinstance(inputs, dict):
        return False

    link = inputs.get("images")
    if not isinstance(link, (list, tuple)) or len(link) < 2:
        return False

    source_id, output_index = link[0], link[1]
    source_node = prompt.get(str(source_id), prompt.get(source_id))
    if not isinstance(source_node, dict):
        return False

    try:
        output_index = int(output_index)
    except (TypeError, ValueError):
        return False

    return (
        source_node.get("class_type") == "LXPromptBatch"
        and output_index == PROGRESS_OUTPUT_INDEX
    )


def install_prompt_progress_preview_bridge() -> bool:
    """Selectively retag PreviewImage results fed by LXPromptBatch progress."""

    try:
        import nodes as comfy_nodes
    except Exception as exc:
        print(f"[LX加载提示词] 无法安装进度预览桥接：{exc}")
        return False

    preview_class = comfy_nodes.NODE_CLASS_MAPPINGS.get("PreviewImage")
    if preview_class is None:
        print("[LX加载提示词] 未找到系统“预览图像”节点，跳过进度预览桥接。")
        return False
    if getattr(preview_class, "_lx_prompt_progress_bridge", False):
        return True

    original_input_types = preview_class.INPUT_TYPES
    original_save_images = preview_class.save_images

    @classmethod
    def bridged_input_types(cls):
        input_types = original_input_types()
        copied: Dict[str, Any] = {
            key: dict(value) if isinstance(value, dict) else value
            for key, value in input_types.items()
        }
        hidden = dict(copied.get("hidden") or {})
        hidden["unique_id"] = "UNIQUE_ID"
        copied["hidden"] = hidden
        return copied

    def bridged_save_images(
        self,
        images,
        prompt=None,
        extra_pnginfo=None,
        unique_id=None,
    ):
        result = original_save_images(
            self,
            images,
            prompt=prompt,
            extra_pnginfo=extra_pnginfo,
        )
        if not _is_prompt_progress_link(prompt, unique_id):
            return result

        ui = result.get("ui") if isinstance(result, dict) else None
        if isinstance(ui, dict) and "images" in ui:
            ui[PROGRESS_UI_KEY] = ui.pop("images")
        return result

    preview_class.INPUT_TYPES = bridged_input_types
    preview_class.save_images = bridged_save_images
    preview_class._lx_prompt_progress_bridge = True
    return True


__all__ = [
    "PROGRESS_UI_KEY",
    "install_prompt_progress_preview_bridge",
]
