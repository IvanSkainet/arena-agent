# ruff: noqa: F821
"""Legacy handler registry wiring facade extracted from unified_bridge.py."""
from __future__ import annotations

from collections.abc import MutableMapping
from typing import Any, Callable

from arena.wiring.legacy_core import build_legacy_core_registries
from arena.wiring.legacy_observability import build_legacy_observability_registries
from arena.wiring.legacy_ops import build_legacy_ops_registries
from arena.wiring.legacy_platform import build_legacy_platform_registries


def build_early_handler_registries(g: MutableMapping[str, Any]) -> dict[str, Callable]:
    """Build handler registries that only depend on already-initialized runtime state."""
    registry: dict[str, Callable] = {}
    registry.update(build_legacy_core_registries(g))
    registry.update(build_legacy_ops_registries(g))
    registry.update(build_legacy_platform_registries(g))
    registry.update(build_legacy_observability_registries(g))
    return registry


__all__ = ["build_early_handler_registries"]
