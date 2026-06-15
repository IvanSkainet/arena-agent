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

# --- Domain wiring builders -------------------------------------------------

@dataclass(frozen=True)
class PublicWiringContext:
    record_request: Callable[..., None]
    cors_json_response: Callable[..., Any]
    metrics: dict[str, Any]
    version: str
    now: Callable[[], float]
    hostname: Callable[[], str]
    bridge_port: Callable[[], int]


def build_public_handlers(ctx: PublicWiringContext) -> dict[str, Callable[..., Any]]:
    """Build public/index/health/API-doc handlers for the route registry."""
    from arena.handler_context import PublicHandlerContext
    from arena.public.handlers import make_public_handlers

    public_ctx = PublicHandlerContext(
        record_request=ctx.record_request,
        cors_json_response=ctx.cors_json_response,
        metrics=ctx.metrics,
        version=ctx.version,
        now=ctx.now,
        hostname=ctx.hostname,
        bridge_port=ctx.bridge_port,
    )
    handlers = make_public_handlers(public_ctx)
    return {
        "handle_index": handlers.index,
        "handle_health": handlers.health,
        "handle_api_docs": handlers.api_docs,
    }


@dataclass(frozen=True)
class SystemWiringContext:
    require_auth: Callable[..., Any]
    record_request: Callable[..., None]
    cors_json_response: Callable[..., Any]
    executor: Any
    common_status: Callable[[dict[str, Any]], dict[str, Any]]
    version: str
    clean_platform_name: Callable[[], str]
    doctor_sync: Callable[[str], dict[str, Any]]
    sysinfo_sync: Callable[..., dict[str, Any]]
    play_beep_sync: Callable[..., dict[str, Any]]


def build_system_handlers(ctx: SystemWiringContext) -> dict[str, Callable[..., Any]]:
    """Build system/status/doctor/sysinfo/beep handlers."""
    from arena.handler_context import SystemHandlerContext
    from arena.system.handlers import make_system_handlers

    system_ctx = SystemHandlerContext(
        require_auth=ctx.require_auth,
        record_request=ctx.record_request,
        cors_json_response=ctx.cors_json_response,
        executor=ctx.executor,
        common_status=ctx.common_status,
        version=ctx.version,
        clean_platform_name=ctx.clean_platform_name,
        doctor_sync=ctx.doctor_sync,
        sysinfo_sync=ctx.sysinfo_sync,
        play_beep_sync=ctx.play_beep_sync,
    )
    handlers = make_system_handlers(system_ctx)
    return {
        "handle_v1_version": handlers.version,
        "handle_v1_info": handlers.info,
        "handle_v1_status": handlers.status,
        "handle_v1_config": handlers.config,
        "handle_v1_doctor": handlers.doctor,
        "handle_v1_sysinfo": handlers.sysinfo,
        "handle_v1_beep": handlers.beep,
    }


@dataclass(frozen=True)
class ServiceWiringContext:
    require_auth: Callable[..., Any]
    record_request: Callable[..., None]
    cors_json_response: Callable[..., Any]
    executor: Any
    service_info_sync: Callable[[], dict[str, Any]]
    sys_svc_sync: Callable[[], dict[str, Any]]
    capabilities_sync: Callable[[], dict[str, Any]]
    spawn_respawn_helper: Callable[[int], tuple[bool, str]]
    audit: Callable[[dict[str, Any]], None]


def build_service_handlers(ctx: ServiceWiringContext) -> dict[str, Callable[..., Any]]:
    """Build service/capabilities/restart handlers."""
    from arena.handler_context import ServiceHandlerContext
    from arena.service.handlers import make_service_handlers

    service_ctx = ServiceHandlerContext(
        require_auth=ctx.require_auth,
        record_request=ctx.record_request,
        cors_json_response=ctx.cors_json_response,
        executor=ctx.executor,
        service_info_sync=ctx.service_info_sync,
        sys_svc_sync=ctx.sys_svc_sync,
        capabilities_sync=ctx.capabilities_sync,
        spawn_respawn_helper=ctx.spawn_respawn_helper,
        audit=ctx.audit,
    )
    handlers = make_service_handlers(service_ctx)
    return {
        "handle_v1_service_info": handlers.service_info,
        "handle_v1_sys_svc": handlers.sys_svc,
        "handle_v1_capabilities": handlers.capabilities,
        "handle_v1_restart": handlers.restart,
    }


@dataclass(frozen=True)
class AdminWiringContext:
    require_auth: Callable[..., Any]
    record_request: Callable[..., None]
    cors_json_response: Callable[..., Any]
    executor: Any
    audit: Callable[[dict[str, Any]], None]
    default_token_file: Any
    root_agent: Any
    subprocess_kwargs: Callable[[], dict[str, Any]]


def build_admin_handlers(ctx: AdminWiringContext) -> dict[str, Callable[..., Any]]:
    """Build admin/tunnel/token handlers."""
    from arena.admin.handlers import make_admin_handlers
    from arena.handler_context import AdminHandlerContext

    admin_ctx = AdminHandlerContext(
        require_auth=ctx.require_auth,
        record_request=ctx.record_request,
        cors_json_response=ctx.cors_json_response,
        executor=ctx.executor,
        audit=ctx.audit,
        default_token_file=ctx.default_token_file,
        root_agent=ctx.root_agent,
        subprocess_kwargs=ctx.subprocess_kwargs,
    )
    handlers = make_admin_handlers(admin_ctx)
    return {
        "handle_v1_sys_funnel": handlers.sys_funnel,
        "handle_v1_token_regenerate": handlers.token_regenerate,
        "handle_v1_tailscale_funnel": handlers.tailscale_funnel,
        "handle_v1_cloudflared_tunnel": handlers.cloudflared_tunnel,
    }


def build_context_handlers(
    context_type: Callable[..., Any],
    factory: Callable[[Any], Any],
    context_kwargs: Mapping[str, Any],
    attr_map: Mapping[str, str],
) -> dict[str, Callable[..., Any]]:
    """Generic builder for already-extracted handler factories.

    This is an incremental container migration helper: unified_bridge.py still
    provides dependency values, while arena.container owns context construction
    and handler attribute mapping.
    """
    ctx = context_type(**dict(context_kwargs))
    built = factory(ctx)
    return {route_name: getattr(built, attr_name) for route_name, attr_name in attr_map.items()}
