# ruff: noqa: F821
"""Legacy platform handler registry wiring."""
from __future__ import annotations

from collections.abc import MutableMapping
from typing import Any, Callable


def build_legacy_platform_registries(g: MutableMapping[str, Any]) -> dict[str, Callable]:
    globals().update(g)
    registry: dict[str, Callable] = {}

    _profile_handler_registry = build_context_handlers(
        ProfileHandlerContext,
        make_profile_handlers,
        {
            "require_auth": require_auth,
            "record_request": _record_request,
            "cors_json_response": _cors_json_response,
            "profiles_dir": _PROFILES_DIR,
            "ensure_profiles_dir": _ensure_profiles_dir,
            "cdp_state": _cdp_state,
            "cdp_active_tab": lambda *args, **kwargs: g["_cdp_active_tab"](*args, **kwargs),
            "version": VERSION,
            "utc_now": utc_now,
            "audit": audit,
            "emit_event": emit_event,
            "log_warning": log.warning,
        },
        {
            "handle_v1_profiles": "profiles",
            "handle_v1_profiles_load": "load",
        },
    )
    registry.update(_profile_handler_registry)


    _grpc_handler_registry = build_context_handlers(
        GrpcHandlerContext,
        make_grpc_handlers,
        {
            "require_auth": require_auth,
            "record_request": _record_request,
            "cors_json_response": _cors_json_response,
            "server_task": _grpc_server_task,
            "start_server": lambda cfg: start_grpc_server(cfg, log_info=log.info, log_error=log.error),
            "stop_server": stop_grpc_server,
        },
        {"handle_v1_grpc": "grpc"},
    )
    registry.update(_grpc_handler_registry)


    _event_handler_registry = build_context_handlers(
        EventHandlerContext,
        make_event_handlers,
        {
            "require_auth": require_auth,
            "version": VERSION,
            "utc_now": utc_now,
            "log_info": log.info,
        },
        {"handle_v1_events": "events"},
    )
    registry.update(_event_handler_registry)


    _watchdog_handler_registry = build_context_handlers(
        WatchdogHandlerContext,
        make_watchdog_handlers,
        {
            "require_auth": require_auth,
            "record_request": _record_request,
            "cors_json_response": _cors_json_response,
            "metrics": BRIDGE_METRICS,
            "now": time.time,
            "log_info": log.info,
        },
        {"handle_v1_watchdog": "watchdog"},
    )
    registry.update(_watchdog_handler_registry)


    _gui_handler_registry = build_context_handlers(
        GuiHandlerContext,
        make_gui_handlers,
        {
            "cors_json_response": _cors_json_response,
            "bridge_dir": BRIDGE_DIR,
            "version": VERSION,
        },
        {
            "handle_gui": "gui",
            "handle_gui_v2": "gui_v2",
            "handle_gui_asset": "gui_asset",
        },
    )
    registry.update(_gui_handler_registry)
    return registry
