"""platform handler registry wiring."""
from __future__ import annotations

from collections.abc import MutableMapping
from typing import Any, Callable

from arena.wiring.env import RuntimeEnv


def build_platform_registries(g: MutableMapping[str, Any]) -> dict[str, Callable]:
    env = RuntimeEnv(g)
    registry: dict[str, Callable] = {}

    _profile_handler_registry = env.build_context_handlers(
        env.ProfileHandlerContext,
        env.make_profile_handlers,
        {
            "require_auth": env.require_auth,
            "record_request": env._record_request,
            "cors_json_response": env._cors_json_response,
            "profiles_dir": env._PROFILES_DIR,
            "ensure_profiles_dir": env._ensure_profiles_dir,
            "cdp_state": env._cdp_state,
            "cdp_active_tab": lambda *args, **kwargs: g["_cdp_active_tab"](*args, **kwargs),
            "version": env.VERSION,
            "utc_now": env.utc_now,
            "audit": env.audit,
            "emit_event": env.emit_event,
            "log_warning": env.log.warning,
        },
        {
            "handle_v1_profiles": "profiles",
            "handle_v1_profiles_load": "load",
        },
    )
    registry.update(_profile_handler_registry)


    _grpc_handler_registry = env.build_context_handlers(
        env.GrpcHandlerContext,
        env.make_grpc_handlers,
        {
            "require_auth": env.require_auth,
            "record_request": env._record_request,
            "cors_json_response": env._cors_json_response,
            "server_task": env._grpc_server_task,
            "start_server": lambda cfg: env.start_grpc_server(cfg, log_info=env.log.info, log_error=env.log.error),
            "stop_server": env.stop_grpc_server,
        },
        {"handle_v1_grpc": "grpc"},
    )
    registry.update(_grpc_handler_registry)


    _event_handler_registry = env.build_context_handlers(
        env.EventHandlerContext,
        env.make_event_handlers,
        {
            "require_auth": env.require_auth,
            "version": env.VERSION,
            "utc_now": env.utc_now,
            "log_info": env.log.info,
        },
        {"handle_v1_events": "events"},
    )
    registry.update(_event_handler_registry)


    _watchdog_handler_registry = env.build_context_handlers(
        env.WatchdogHandlerContext,
        env.make_watchdog_handlers,
        {
            "require_auth": env.require_auth,
            "record_request": env._record_request,
            "cors_json_response": env._cors_json_response,
            "metrics": env.BRIDGE_METRICS,
            "now": env.time.time,
            "log_info": env.log.info,
        },
        {"handle_v1_watchdog": "watchdog"},
    )
    registry.update(_watchdog_handler_registry)


    _gui_handler_registry = env.build_context_handlers(
        env.GuiHandlerContext,
        env.make_gui_handlers,
        {
            "cors_json_response": env._cors_json_response,
            "bridge_dir": env.BRIDGE_DIR,
            "version": env.VERSION,
        },
        {
            "handle_gui": "gui",
            "handle_gui_v2": "gui_v2",
            "handle_gui_asset": "gui_asset",
        },
    )
    registry.update(_gui_handler_registry)
    return registry
