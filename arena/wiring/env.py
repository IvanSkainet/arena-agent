"""Typed-ish access wrapper for transitional runtime wiring mappings."""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any


class RuntimeEnv:
    """Attribute access for runtime composition values.

    This replaces the old ``globals().update(g)`` pattern in transitional wiring
    modules.  Missing names fail loudly with a useful AttributeError while the
    call sites become explicit: ``env.require_auth`` instead of a hidden global.
    """

    def __init__(self, values: Mapping[str, Any]):
        self._values = values

    def __getattr__(self, name: str) -> Any:
        try:
            return self._values[name]
        except KeyError as exc:
            raise AttributeError(name) from exc
