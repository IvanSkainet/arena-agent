"""Boundary-only compatibility exports for historical unified_bridge imports.

Runtime composition imports ``arena.runtime_deps`` directly.  This package exists
only for external code that deliberately wants the old broad import surface.
"""
from __future__ import annotations

from arena.runtime_deps import *  # noqa: F401,F403

__all__ = [name for name in globals() if not name.startswith("__")]
