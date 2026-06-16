"""Runtime dependency namespace for the unified_bridge compatibility facade.

The production modules live in focused ``arena/<domain>`` packages.  This
namespace exists so the thin ``unified_bridge.py`` facade can assemble its
runtime and historical re-export surface without becoming a giant import block.
"""
from __future__ import annotations

from arena.runtime_deps.stdlib import *  # noqa: F401,F403
from arena.runtime_deps.core import *  # noqa: F401,F403
from arena.runtime_deps.domains import *  # noqa: F401,F403
from arena.runtime_deps.observability_system_wiring import *  # noqa: F401,F403

__all__ = [name for name in globals() if not name.startswith("__")]
