class GlobalInput:
    SEARCH_ALIASES = [
        "lx",
        "LX",
        "灵犀",
        "全局输入",
        "GlobalInput",
        "Global Input",
        "global_input",
        "broadcast input",
    ]

    @classmethod
    def INPUT_TYPES(cls):
        return {"optional": {"anything": ("*",)}}

    RETURN_TYPES = ()
    FUNCTION = "execute"
    CATEGORY = "🅻🆇 灵犀/全局输入"
    DESCRIPTION = "将已连接的值广播到同类型的未连接输入。"

    def execute(self, **kwargs):
        return ()


class BroadcastBlock:
    SEARCH_ALIASES = [
        "lx",
        "LX",
        "灵犀",
        "屏蔽广播",
        "BroadcastBlock",
        "Broadcast Block",
        "broadcast_block",
        "block broadcast",
    ]

    @classmethod
    def INPUT_TYPES(cls):
        return {}

    RETURN_TYPES = ("*",)
    RETURN_NAMES = ("anything",)
    FUNCTION = "execute"
    CATEGORY = "🅻🆇 灵犀/全局输入"
    DESCRIPTION = "占位输出节点，用于阻断某一路全局广播。"

    def execute(self):
        return (None,)
