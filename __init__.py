"""ComfyUI-LX-Nodes core package.

Loads the LX utility, image batch, and relay modules from one package.
"""

import importlib
import os
import sys

_PACKAGE_NAME = "_lx_nodes_plugins"
_package_dir = os.path.dirname(os.path.abspath(__file__))
_plugins_base = os.path.join(_package_dir, "_plugins")


def _ensure_plugins_parent():
    """Load the private runtime package for modules under ``_plugins/``.

    The on-disk directory stays named ``_plugins``. At runtime it is exposed as
    ``_lx_nodes_plugins`` to avoid collisions with other ComfyUI custom nodes.
    """
    if _PACKAGE_NAME in sys.modules:
        return
    init_file = os.path.join(_plugins_base, "__init__.py")
    if os.path.isfile(init_file):
        spec = importlib.util.spec_from_file_location(
            _PACKAGE_NAME,
            init_file,
            submodule_search_locations=[_plugins_base],
        )
        if spec and spec.loader:
            parent_mod = importlib.util.module_from_spec(spec)
            sys.modules[_PACKAGE_NAME] = parent_mod
            spec.loader.exec_module(parent_mod)


# ── 动态发现所有插件（仅扫描 _plugins/）───────────────────────────────────────
_plugin_subdirs = []
if os.path.isdir(_plugins_base):
    for _name in sorted(os.listdir(_plugins_base)):
        _path = os.path.join(_plugins_base, _name)
        if os.path.isdir(_path) and not _name.startswith("_"):
            _plugin_subdirs.append((_name, _path))

NODE_CLASS_MAPPINGS = {}
NODE_DISPLAY_NAME_MAPPINGS = {}
_node_key_sources = {}

_ensure_plugins_parent()

for _name, _path in _plugin_subdirs:
    _module_name = f"{_PACKAGE_NAME}.{_name}"
    try:
        _mod = importlib.import_module(_module_name)
    except Exception as _e:
        print(f"[灵犀节点] 插件 {_module_name!r} 加载失败，已跳过。错误: {_e}")
        continue

    child_class_mappings = getattr(_mod, "NODE_CLASS_MAPPINGS", {}) or {}
    child_display_mappings = getattr(_mod, "NODE_DISPLAY_NAME_MAPPINGS", {}) or {}
    duplicate_keys = set(NODE_CLASS_MAPPINGS) & set(child_class_mappings)
    if duplicate_keys:
        details = ", ".join(
            f"{key}（已有: {_node_key_sources.get(key, 'unknown')}，新: {_module_name}）"
            for key in sorted(duplicate_keys)
        )
        print(f"[灵犀节点] 插件 {_module_name!r} 存在重复节点 key，已跳过冲突项: {details}")

    for _key, _cls in child_class_mappings.items():
        if _key in NODE_CLASS_MAPPINGS:
            continue
        NODE_CLASS_MAPPINGS[_key] = _cls
        _node_key_sources[_key] = _module_name
        if _key in child_display_mappings:
            NODE_DISPLAY_NAME_MAPPINGS[_key] = child_display_mappings[_key]

    for _key, _display in child_display_mappings.items():
        if _key in NODE_CLASS_MAPPINGS and _key not in NODE_DISPLAY_NAME_MAPPINGS:
            NODE_DISPLAY_NAME_MAPPINGS[_key] = _display

print(f"[灵犀节点] 已加载 {len(NODE_CLASS_MAPPINGS)} 个节点（含 {len(_plugin_subdirs)} 个插件）")

# ── Web 静态资源目录 ─────────────────────────────────────────────────────────
WEB_DIRECTORY = os.path.join(_package_dir, "web")
