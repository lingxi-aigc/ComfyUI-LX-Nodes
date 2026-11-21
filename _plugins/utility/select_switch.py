from __future__ import annotations

from typing import Any

from ..categories import LX_UTILITY_CATEGORY
from .any_switch import ANY, FlexibleOptionalInputType


INPUT_PREFIX = "输入"
SELECT_WIDGET = "选择"


def _input_name(index: int) -> str:
    return f"{INPUT_PREFIX}{index}"


def _input_index(name: str) -> int:
    if name.startswith(INPUT_PREFIX) and name.removeprefix(INPUT_PREFIX).isdigit():
        return int(name.removeprefix(INPUT_PREFIX))
    return 10_000


def _ordered_input_names(kwargs: dict[str, Any]) -> list[str]:
    return sorted(
        [name for name in kwargs if _input_index(name) < 10_000],
        key=_input_index,
    )


def _selected_index(value: Any) -> int:
    try:
        return max(1, int(value))
    except Exception:
        return 1


def _clamped_selected_index(value: Any, input_names: list[str]) -> int:
    max_index = max(1, len(input_names))
    return min(_selected_index(value), max_index)


class LXSelectSwitch:
    """Pass through the manually selected input."""

    CATEGORY = LX_UTILITY_CATEGORY
    DESCRIPTION = "手动选择一路任意类型输入，并原样输出。"
    SEARCH_ALIASES = ["lx", "LX", "灵犀", "切换选择", "选择切换", "select switch"]
    RETURN_TYPES = (ANY,)
    RETURN_NAMES = ("输出",)
    FUNCTION = "switch"

    @classmethod
    def INPUT_TYPES(cls):
        initial_inputs = {
            _input_name(1): (
                ANY,
                {
                    "forceInput": True,
                    "lazy": True,
                    "display_name": _input_name(1),
                    "label": _input_name(1),
                },
            ),
        }
        return {
            "required": {
                SELECT_WIDGET: ("INT", {"default": 1, "min": 1, "max": 1, "step": 1}),
            },
            "optional": FlexibleOptionalInputType(ANY, initial_inputs),
        }

    def check_lazy_status(self, **kwargs):
        input_names = _ordered_input_names(kwargs)
        selected_index = _clamped_selected_index(kwargs.get(SELECT_WIDGET, 1), input_names)
        selected_name = next(
            (name for name in input_names if _input_index(name) == selected_index),
            _input_name(selected_index),
        )
        if selected_name in kwargs and kwargs.get(selected_name) is None:
            return [selected_name]
        return []

    def switch(self, **kwargs):
        input_names = _ordered_input_names(kwargs)
        selected_index = _clamped_selected_index(kwargs.get(SELECT_WIDGET, 1), input_names)
        for name in input_names:
            if _input_index(name) == selected_index:
                return (kwargs.get(name),)
        return (None,)
