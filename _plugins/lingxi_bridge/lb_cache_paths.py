# -*- coding: utf-8 -*-
from __future__ import annotations

import os


CACHE_ROOT_ENV = "LX_RELAY_CACHE_DIR"

_BRIDGE_DIR = os.path.dirname(os.path.realpath(__file__))
_PLUGINS_ROOT = os.path.dirname(_BRIDGE_DIR)
_PACKAGE_ROOT = os.path.dirname(_PLUGINS_ROOT)
_COMFYUI_ROOT = os.path.dirname(os.path.dirname(_PACKAGE_ROOT))

_CACHE_SUBDIRS = {
    "task_queue": "task_queue",
    "concurrent_bridge": "concurrent_bridge",
    "inpaint_api": "inpaint_api",
}

def _default_cache_root() -> str:
    try:
        import folder_paths  # type: ignore[reportMissingImports]

        get_system_user_directory = getattr(folder_paths, "get_system_user_directory", None)
        if callable(get_system_user_directory):
            return os.path.join(get_system_user_directory("lx_relay"), "cache")

        get_user_directory = getattr(folder_paths, "get_user_directory", None)
        if callable(get_user_directory):
            return os.path.join(get_user_directory(), "__lx_relay", "cache")
    except Exception:
        pass

    return os.path.join(_COMFYUI_ROOT, "user", "__lx_relay", "cache")


def get_cache_root(create: bool = False) -> str:
    configured = os.environ.get(CACHE_ROOT_ENV, "").strip()
    root = os.path.abspath(os.path.expanduser(configured)) if configured else _default_cache_root()
    if create:
        os.makedirs(root, exist_ok=True)
    return root


def get_cache_dir(name: str, create: bool = False) -> str:
    subdir = _CACHE_SUBDIRS.get(str(name), str(name))
    path = os.path.join(get_cache_root(create=create), subdir)
    if create:
        os.makedirs(path, exist_ok=True)
    return path
