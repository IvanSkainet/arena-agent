"""Composition container primitives for the Arena bridge.

This module is intentionally small for the first container step: it creates an
explicit object around the legacy handler-global mapping. Later phases can move
runtime/context construction into this container without changing app/routes.
"""
from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any


_ALWAYS_EXPORTED = {
    # Public/non-`handle_` route globals kept for historical names.
    "handle_index",
    "handle_health",
    "handle_api_docs",
    "handle_prometheus_metrics",
    "handle_gateway_index",
    "handle_gateway_tools",
    "handle_gateway_run",
    "handle_gateway_tool",
    "handle_mcp_post",
    "handle_mcp_delete",
    "handle_sse",
    "handle_sse_messages",
    "handle_ws",
    "handle_gui",
    "handle_gui_v2",
}


@dataclass(frozen=True)
class BridgeContainer:
    """Current v3 composition container.

    `handlers` is the route registry input. It is still mapping-based during the
    migration because handler construction currently happens in the compatibility
    entrypoint. This gives us a stable seam for moving that construction next.
    """

    handlers: Mapping[str, Callable[..., Any]]


def build_handler_registry(source: Mapping[str, Any]) -> dict[str, Callable[..., Any]]:
    """Build the handler registry consumed by arena.routes.register_routes."""
    handlers: dict[str, Callable[..., Any]] = {}
    for name, value in source.items():
        if (name.startswith("handle_v") or name in _ALWAYS_EXPORTED) and callable(value):
            handlers[name] = value
    return handlers


def build_container(source: Mapping[str, Any]) -> BridgeContainer:
    """Build the bridge composition container from a legacy globals mapping."""
    return BridgeContainer(handlers=build_handler_registry(source))
