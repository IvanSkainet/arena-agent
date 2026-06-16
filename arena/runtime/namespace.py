"""Runtime namespace construction for the thin unified_bridge facade."""
from __future__ import annotations

import sqlite3
from collections.abc import Mapping, MutableMapping
from types import ModuleType
from typing import Any


def build_runtime_namespace(deps_module: ModuleType) -> dict[str, Any]:
    """Return an isolated dependency namespace for bridge runtime composition.

    The old facade used its own module globals as the composition dictionary.
    Keeping composition data in a separate namespace means runtime construction
    no longer depends on mutating ``unified_bridge`` globals.  Compatibility
    exports are applied afterwards as a boundary concern.
    """
    names = getattr(deps_module, "__all__", None)
    if names is None:
        names = [name for name in vars(deps_module) if not name.startswith("__")]
    namespace = {name: getattr(deps_module, name) for name in names}
    # Historical unified_bridge imported sqlite3 at module level; keep it in the
    # compatibility namespace without making the facade import block grow again.
    namespace.setdefault("sqlite3", sqlite3)
    return namespace


def apply_compat_exports(target: MutableMapping[str, Any], *sources: Mapping[str, Any]) -> None:
    """Export runtime/compatibility names into a facade module namespace."""
    for source in sources:
        for name, value in source.items():
            if name.startswith("__"):
                continue
            target[name] = value
