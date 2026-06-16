"""Core bridge container and generic wiring helpers."""
from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

_ALWAYS_EXPORTED = {
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
    "handle_gui_asset",
}


@dataclass(frozen=True)
class BridgeContainer:
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


def build_context_handlers(
    context_type: Callable[..., Any],
    factory: Callable[[Any], Any],
    context_kwargs: Mapping[str, Any],
    attr_map: Mapping[str, str],
) -> dict[str, Callable[..., Any]]:
    """Generic builder for already-extracted handler factories."""
    ctx = context_type(**dict(context_kwargs))
    built = factory(ctx)
    return {route_name: getattr(built, attr_name) for route_name, attr_name in attr_map.items()}


def export_handler_attrs(target: dict[str, Any], built: Any, attr_map: Mapping[str, str]) -> None:
    """Export selected handler attributes into a legacy globals mapping."""
    for route_name, attr_name in attr_map.items():
        target[route_name] = getattr(built, attr_name)
