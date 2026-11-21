from __future__ import annotations

from comfy_api.latest import io

from ..categories import LX_UTILITY_CATEGORY


class LXBooleanSelect(io.ComfyNode):
    """Select one lazy input by a boolean switch."""

    SEARCH_ALIASES = ["lx", "LX", "灵犀", "布尔选择", "条件选择", "boolean select"]

    @classmethod
    def define_schema(cls):
        template = io.MatchType.Template("lx_boolean_select")
        return io.Schema(
            node_id="LXBooleanSelect",
            display_name="布尔选择",
            category=LX_UTILITY_CATEGORY,
            search_aliases=cls.SEARCH_ALIASES,
            inputs=[
                io.Boolean.Input("switch", display_name="开关", default=True),
                io.MatchType.Input("on_true", template=template, display_name="真", lazy=True),
                io.MatchType.Input("on_false", template=template, display_name="假", lazy=True),
            ],
            outputs=[
                io.MatchType.Output(template=template, display_name="输出"),
            ],
        )

    @classmethod
    def check_lazy_status(cls, switch=True, on_true=None, on_false=None):
        if switch and on_true is None:
            return ["on_true"]
        if not switch and on_false is None:
            return ["on_false"]
        return []

    @classmethod
    def execute(cls, switch=True, on_true=None, on_false=None):
        return io.NodeOutput(on_true if switch else on_false)
