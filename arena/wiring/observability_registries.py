"""observability handler registry wiring."""
from __future__ import annotations

from collections.abc import MutableMapping
from typing import Any, Callable

from arena.wiring.env import RuntimeEnv


def build_observability_registries(g: MutableMapping[str, Any]) -> dict[str, Callable]:
    env = RuntimeEnv(g)
    registry: dict[str, Callable] = {}

    _runtime_observability_handler_registry = env.build_context_handlers(
        env.RuntimeObservabilityHandlerContext,
        env.make_runtime_observability_handlers,
        {
            "require_auth": env.require_auth,
            "record_request": env._record_request,
            "cors_json_response": env._cors_json_response,
            "metrics": env.BRIDGE_METRICS,
            "metrics_lock": env._metrics_lock,
            "active_processes": env.ACTIVE_PROCESSES,
            "cdp_state": env._cdp_state,
            "watchdog_state": env._watchdog_state,
            "event_subscribers": env._event_subscribers,
            "tls_config": env._tls_config,
            "grpc_config": env._grpc_config,
            "cluster_state": env._cluster_state,
            "sandbox_config": env._sandbox_config,
            "otel_config": env._otel_config,
            "log_file": env.LOG_FILE,
            "version": env.VERSION,
            "now": env.time.time,
            "log_error": env.log.error,
        },
        {
            "handle_v1_metrics": "metrics",
            "handle_prometheus_metrics": "prometheus_metrics",
            "handle_v1_logs": "logs",
        },
    )
    registry.update(_runtime_observability_handler_registry)


    _tracing_handler_registry = env.build_context_handlers(
        env.TracingHandlerContext,
        env.make_tracing_handlers,
        {
            "require_auth": env.require_auth,
            "record_request": env._record_request,
            "cors_json_response": env._cors_json_response,
            "version": env.VERSION,
            "log_info": env.log.info,
        },
        {
            "handle_v1_tracing": "tracing",
            "handle_v1_traces_export": "traces_export",
        },
    )
    registry.update(_tracing_handler_registry)


    _user_handler_registry = env.build_context_handlers(
        env.UserHandlerContext,
        env.make_user_handlers,
        {
            "require_auth": env.require_auth,
            "record_request": env._record_request,
            "cors_json_response": env._cors_json_response,
            "check_auth_with_role": env.check_auth_with_role,
            "list_users": env._user_store.list_users_for_response,
            "add_or_update_user": env._user_store.add_or_update_user,
            "remove_user": env._user_store.remove_user,
            "token_generator": env.b64_token,
            "audit": env.audit,
            "log_info": env.log.info,
        },
        {"handle_v1_users": "users"},
    )
    registry.update(_user_handler_registry)


    _file_handler_registry = env.build_context_handlers(
        env.FileHandlerContext,
        env.make_file_handlers,
        {
            "require_auth": env.require_auth,
            "record_request": env._record_request,
            "cors_json_response": env._cors_json_response,
            "audit": env.audit,
            "home": env.Path.home(),
            "bridge_py": env.Path(__file__).resolve(),
        },
        {
            "handle_v1_upload": "upload",
            "handle_v1_download": "download",
        },
    )
    registry.update(_file_handler_registry)
    return registry
