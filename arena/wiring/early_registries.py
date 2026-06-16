"""handler registry wiring facade extracted from unified_bridge.py."""
from __future__ import annotations

from collections.abc import MutableMapping
from typing import Any, Callable

from arena.wiring.core_registries import build_core_registries
from arena.wiring.observability_registries import build_observability_registries
from arena.wiring.ops_registries import build_ops_registries
from arena.wiring.platform_registries import build_platform_registries


def build_early_handler_registries(g: MutableMapping[str, Any]) -> dict[str, Callable]:
    """Build handler registries that only depend on already-initialized runtime state."""
    registry: dict[str, Callable] = {}
    registry.update(build_core_registries(g))
    registry.update(build_ops_registries(g))
    registry.update(build_platform_registries(g))
    registry.update(build_observability_registries(g))
    return registry


__all__ = ["build_early_handler_registries"]
