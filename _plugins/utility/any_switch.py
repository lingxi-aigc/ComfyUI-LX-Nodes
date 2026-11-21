from __future__ import annotations

from typing import Any

from comfy_execution.graph_utils import is_link
from comfy_execution.utils import get_executing_context

from ..categories import LX_UTILITY_CATEGORY


class AnyType(str):
    def __ne__(self, value: object) -> bool:
        return False


class FlexibleOptionalInputType(dict):
    """Accept dynamically-added optional inputs from the frontend."""

    def __init__(self, input_type: Any, data: dict[str, tuple[Any, dict[str, Any]]] | None = None):
        super().__init__()
        self.input_type = input_type
        self.data = data or {}
        self.update(self.data)

    def __getitem__(self, key: str):
        if key in self.data:
            return self.data[key]
        return (self.input_type, {"forceInput": True, "lazy": True})

    def __contains__(self, key: object) -> bool:
        return True


ANY = AnyType("*")
INPUT_PREFIX = "输入"
MIN_INPUTS = 5


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


def _is_empty(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return value == ""
    if isinstance(value, (list, tuple, dict, set)):
        return len(value) == 0
    return False


class LXAnySwitch:
    """Pass through the first non-empty input from top to bottom."""

    CATEGORY = LX_UTILITY_CATEGORY
    DESCRIPTION = "从上到下选择第一个有效的任意类型输入，并原样输出。"
    SEARCH_ALIASES = ["lx", "LX", "灵犀", "切换任意", "任意切换", "任意选择", "any switch"]
    RETURN_TYPES = (ANY,)
    RETURN_NAMES = ("输出",)
    FUNCTION = "switch"

    def __init__(self):
        self._lazy_scope = None
        self._requested_lazy_inputs: dict[int | None, set[str]] = {}

    @classmethod
    def INPUT_TYPES(cls):
        initial_inputs = {
            _input_name(index): (
                ANY,
                {
                    "forceInput": True,
                    "lazy": True,
                    "display_name": _input_name(index),
                    "label": _input_name(index),
                },
            )
            for index in range(1, MIN_INPUTS + 1)
        }
        return {
            "required": {},
            "optional": FlexibleOptionalInputType(ANY, initial_inputs),
            "hidden": {"execution_list": "EXECUTION_LIST", "unique_id": "UNIQUE_ID"},
        }

    def check_lazy_status(self, execution_list=None, unique_id=None, **kwargs):
        input_names = _ordered_input_names(kwargs)
        if execution_list is not None and unique_id is not None:
            connections = execution_list.dynprompt.get_node(unique_id)["inputs"]
            for name in input_names:
                value = kwargs[name]
                if not _is_empty(value):
                    return []
                link = connections.get(name)
                if value is None and is_link(link):
                    cached = execution_list.get_cache(link[0], unique_id)
                    # An evaluated None is empty; an unresolved link still needs to run.
                    if cached is None or cached.outputs is None or link[1] >= len(cached.outputs):
                        return [name]
            return []

        # Older ComfyUI versions do not pass the execution list.
        context = get_executing_context()
        task = (context.prompt_id, context.node_id) if context is not None else None
        scope = (task, tuple(input_names))
        if scope != self._lazy_scope:
            self._lazy_scope = scope
            self._requested_lazy_inputs.clear()

        list_index = context.list_index if context is not None else None
        requested = self._requested_lazy_inputs.setdefault(list_index, set())
        for name in input_names:
            value = kwargs[name]
            if not _is_empty(value):
                return []
            if value is None and name not in requested:
                requested.add(name)
                return [name]
        return []

    def switch(self, **kwargs):
        self._requested_lazy_inputs.clear()
        self._lazy_scope = None
        for name in _ordered_input_names(kwargs):
            value = kwargs.get(name)
            if not _is_empty(value):
                return (value,)
        return (None,)
