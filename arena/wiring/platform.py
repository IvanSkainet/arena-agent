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
    sys_funnel_status_sync: Any = None
    cloudflared_status_sync: Any = None
    zerotier_status_sync: Any = None
    tailscale_funnel_action_sync: Any = None
    cloudflared_funnel_action_sync: Any = None


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
        sys_funnel_status_sync=ctx.sys_funnel_status_sync,
        cloudflared_status_sync=ctx.cloudflared_status_sync,
        zerotier_status_sync=ctx.zerotier_status_sync,
        tailscale_funnel_action_sync=ctx.tailscale_funnel_action_sync,
        cloudflared_funnel_action_sync=ctx.cloudflared_funnel_action_sync,
    )
    handlers = make_admin_handlers(admin_ctx)
    return {
        "handle_v1_sys_funnel": handlers.sys_funnel,
        "handle_v1_token_regenerate": handlers.token_regenerate,
        "handle_v1_tailscale_funnel": handlers.tailscale_funnel,
        "handle_v1_cloudflared_tunnel": handlers.cloudflared_tunnel,
        "handle_v1_zerotier_status": handlers.zerotier_status,
        "handle_v1_zerotier_network": handlers.zerotier_network,
        "handle_v1_tunnels_status": handlers.tunnels_status,
        "handle_v1_tunnels_active": handlers.tunnels_active,
        "handle_v1_tunnels_start": handlers.tunnels_start,
        "handle_v1_tunnels_stop": handlers.tunnels_stop,
    }


@dataclass(frozen=True)
class MobileWiringContext:
    require_auth: Callable[..., Any]
    record_request: Callable[..., None]
    cors_json_response: Callable[..., Any]
    executor: Any
    audit: Callable[[dict[str, Any]], None]


def build_mobile_handlers(ctx: MobileWiringContext) -> dict[str, Callable[..., Any]]:
    """Wire /v1/mobile/* handlers. No sync callables needed — every mobile
    module talks to adb via subprocess directly, cross-platform."""
    from arena.mobile.handlers import make_mobile_handlers

    class _Ctx:
        """Duck-typed context that make_mobile_handlers uses."""
        def __init__(self, w):
            self.require_auth = w.require_auth
            self.record_request = w.record_request
            self.cors_json_response = w.cors_json_response
            self.executor = w.executor
            self.audit = w.audit

    handlers = make_mobile_handlers(_Ctx(ctx))
    return {
        "handle_v1_mobile_devices": handlers.list_devices,
        "handle_v1_mobile_info": handlers.device_info,
        "handle_v1_mobile_screenshot": handlers.screenshot,
        "handle_v1_mobile_tap": handlers.tap,
        "handle_v1_mobile_swipe": handlers.swipe,
        "handle_v1_mobile_type": handlers.type_text,
        "handle_v1_mobile_key": handlers.key_event,
        "handle_v1_mobile_shell": handlers.shell,
        "handle_v1_mobile_packages": handlers.packages,
        "handle_v1_mobile_gesture": handlers.gesture,
        "handle_v1_mobile_ui": handlers.ui_dump,
        "handle_v1_mobile_tap_by": handlers.tap_by,
        "handle_v1_mobile_helpers_status": handlers.helpers_status,
        "handle_v1_mobile_helpers_install": handlers.helpers_install,
        "handle_v1_mobile_ime_status": handlers.ime_status,
        "handle_v1_mobile_ime_set": handlers.ime_set,
        "handle_v1_mobile_ime_reset": handlers.ime_reset,
        "handle_v1_mobile_paste": handlers.paste,
        "handle_v1_mobile_sensors": handlers.sensors,
        "handle_v1_mobile_scroll": handlers.scroll,
        "handle_v1_mobile_key_combo": handlers.key_combo,
        "handle_v1_mobile_pair": handlers.pair,
        "handle_v1_mobile_connect": handlers.connect,
        "handle_v1_mobile_disconnect": handlers.disconnect,
        "handle_v1_mobile_apk_prepare": handlers.apk_prepare,
        "handle_v1_mobile_apk_install": handlers.apk_install,
        "handle_v1_mobile_batch": handlers.batch,
    }
