from __future__ import annotations

from ..categories import LX_TEXT_CATEGORY


MAX_PROMPTS = 32
DEFAULT_PROMPTS = 5


def _coerce_count(value: int | str | float | None) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _clamp_count(value: int | str | float | None, fallback: int = DEFAULT_PROMPTS) -> int:
    count = _coerce_count(value)
    if count is None:
        count = fallback
    return max(1, min(MAX_PROMPTS, count))


def _to_text(value: object) -> str:
    return "" if value is None else str(value)


def _prompt_display_name(index: int) -> str:
    return f"提示词{index}"


def _node_inputs_from_prompt(prompt: object, unique_id: object) -> dict:
    if not isinstance(prompt, dict) or unique_id is None:
        return {}

    node = prompt.get(str(unique_id)) or prompt.get(unique_id)
    if not isinstance(node, dict):
        return {}

    inputs = node.get("inputs")
    return inputs if isinstance(inputs, dict) else {}


def _node_properties_from_workflow(extra_pnginfo: object, unique_id: object) -> dict:
    if not isinstance(extra_pnginfo, dict) or unique_id is None:
        return {}

    workflow = extra_pnginfo.get("workflow")
    if not isinstance(workflow, dict):
        return {}

    for node in workflow.get("nodes", []):
        if not isinstance(node, dict) or str(node.get("id")) != str(unique_id):
            continue

        properties = node.get("properties")
        return properties if isinstance(properties, dict) else {}

    return {}


class LXPromptList:
    """Collect prompt text boxes into one list output and one string-list output."""

    CATEGORY = LX_TEXT_CATEGORY
    SEARCH_ALIASES = ["lx", "LX", "灵犀", "提示词列表", "提示词批量", "prompt list"]
    RETURN_TYPES = ("LIST", "STRING")
    RETURN_NAMES = ("列表", "prompt_strings")
    OUTPUT_IS_LIST = (False, True)
    FUNCTION = "collect"

    @classmethod
    def INPUT_TYPES(cls):
        optional = {}
        for index in range(1, MAX_PROMPTS + 1):
            name = f"prompt_{index}"
            optional[f"prompt_{index}"] = (
                "STRING",
                {
                    "default": "",
                    "multiline": True,
                    "display_name": _prompt_display_name(index),
                    "label": _prompt_display_name(index),
                },
            )

        optional["数量"] = (
            "INT",
            {
                "default": DEFAULT_PROMPTS,
                "min": 1,
                "max": MAX_PROMPTS,
                "step": 1,
            },
        )

        return {
            "optional": optional,
            "hidden": {
                "prompt": "PROMPT",
                "unique_id": "UNIQUE_ID",
                "extra_pnginfo": "EXTRA_PNGINFO",
            },
        }

    def collect(
        self,
        数量=DEFAULT_PROMPTS,
        prompt=None,
        unique_id=None,
        extra_pnginfo=None,
        **kwargs,
    ):
        prompt_inputs = _node_inputs_from_prompt(prompt, unique_id)
        workflow_properties = _node_properties_from_workflow(extra_pnginfo, unique_id)
        saved_count = _clamp_count(workflow_properties.get("lx_prompt_list_count"))
        count = _clamp_count(数量, saved_count)
        workflow_values = workflow_properties.get("lx_prompt_list_values", {})
        if not isinstance(workflow_values, dict):
            workflow_values = {}

        prompts = []
        for index in range(1, count + 1):
            name = f"prompt_{index}"
            value = kwargs.get(name)
            if value is None:
                value = prompt_inputs.get(name)
            if value is None:
                value = workflow_values.get(name)

            text = _to_text(value).strip()
            if text:
                prompts.append(text)

        return (prompts, prompts)
