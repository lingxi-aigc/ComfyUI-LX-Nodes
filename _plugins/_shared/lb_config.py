"""Compatibility exports for old LX shared config imports.

Relay route registration belongs to the integrated ``lingxi_bridge`` module.
Current LX-Nodes code should import shared secret helpers from ``.secrets``
with relative imports instead.
"""

from __future__ import annotations

from .secrets import *  # noqa: F401,F403
from .secrets import __all__ as _secret_exports


def register_routes():
    """No-op compatibility shim for old imports.

    The active ``/relayapi`` routes are registered by ``lingxi_bridge``.
    """
    print("[LX][shared] relay routes are registered by lingxi_bridge")


__all__ = [*_secret_exports, "register_routes"]
