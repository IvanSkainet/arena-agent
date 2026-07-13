"""System/service/admin route handler wiring."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any


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
        "handle_v1_zerotier_status": handlers.zerotier_status,
        "handle_v1_zerotier_network": handlers.zerotier_network,
    }
