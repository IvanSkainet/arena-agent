"""Compatibility import surface for unified_bridge.py.

Kept separate from the entrypoint so unified_bridge can become a thin facade
while still re-exporting historical imports and helper names.
"""
from __future__ import annotations

from arena.legacy_imports.stdlib import *  # noqa: F401,F403
from arena.legacy_imports.core import *  # noqa: F401,F403
from arena.legacy_imports.domains import *  # noqa: F401,F403
from arena.legacy_imports.observability_system_wiring import *  # noqa: F401,F403

__all__ = [name for name in globals() if not name.startswith("__")]
