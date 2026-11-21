"""Frontend-only group control nodes for LX-Nodes.

The actual frontend extension loaded by ComfyUI is mirrored at
``web/group_control/group_control.js`` because the top-level package exposes a
single ``WEB_DIRECTORY``.
"""

NODE_CLASS_MAPPINGS = {}
NODE_DISPLAY_NAME_MAPPINGS = {}

__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS"]
