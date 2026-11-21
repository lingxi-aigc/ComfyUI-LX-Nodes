from .global_input import GlobalInput, BroadcastBlock

PLUGIN_VERSION = "1.0.0"
WEB_DIRECTORY = "./js"

NODE_CLASS_MAPPINGS = {
    "GlobalInput": GlobalInput,
    "BroadcastBlock": BroadcastBlock,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "GlobalInput": "全局输入",
    "BroadcastBlock": "屏蔽广播",
}

__all__ = ["WEB_DIRECTORY", "NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS"]
