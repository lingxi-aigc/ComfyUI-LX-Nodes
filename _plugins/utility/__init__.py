"""Utility nodes for LX-Nodes (preview, judge, cleanup, etc.)."""

from importlib import import_module


NODE_CLASS_MAPPINGS = {}
NODE_DISPLAY_NAME_MAPPINGS = {}


def _register_node(module_name, class_name, node_key, display_name):
    try:
        module = import_module(f"{__name__}.{module_name}")
        node_class = getattr(module, class_name)
    except Exception as exc:
        print(f"[灵犀节点] 实用工具节点 {node_key} 加载失败，已跳过: {exc}")
        return None
    NODE_CLASS_MAPPINGS[node_key] = node_class
    NODE_DISPLAY_NAME_MAPPINGS[node_key] = display_name
    return module


_register_node("any_switch", "LXAnySwitch", "LXAnySwitch", "切换任意")
_register_node("boolean_select", "LXBooleanSelect", "LXBooleanSelect", "布尔选择")
_register_node("show_any", "LXShowAny", "LXShowAny", "展示任意")
_register_node("show_text", "LXShowText", "LXShowText", "展示文本")
_register_node("environment_diagnostics", "LXEnvironmentDiagnostics", "LXEnvironmentDiagnostics", "灵犀环境诊断")
_register_node("qwen3vl_reverse", "LXQwen3VLReverse", "LXQwen3VLReverse", "Qwen3VL 图像反推")
_register_node("qwen_text_generate", "LXQwenTextGenerate", "LXQwenTextGenerate", "Qwen3 文本生成")
_register_node("select_switch", "LXSelectSwitch", "LXSelectSwitch", "切换选择")
_memory_release_module = _register_node("memory_release", "LXMemoryRelease", "LXMemoryRelease", "显存/内存释放")

if _memory_release_module is not None:
    try:
        _memory_release_module.register_memory_cleanup_routes()
    except Exception as exc:
        print(f"[灵犀节点] 内存清理路由注册失败，节点仍会加载: {exc}")

try:
    _execution_control_module = import_module(f"{__name__}.execution_control")
    _execution_control_module.register_execution_control_routes()
except Exception as exc:
    print(f"[灵犀节点] 强制停止路由注册失败，其他实用工具仍会加载: {exc}")

__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS"]
