"""Legacy observability handler registry wiring."""
from __future__ import annotations

from collections.abc import MutableMapping
from typing import Any, Callable


def build_legacy_observability_registries(g: MutableMapping[str, Any]) -> dict[str, Callable]:
    globals().update(g)
    registry: dict[str, Callable] = {}

    _runtime_observability_handler_registry = build_context_handlers(
        RuntimeObservabilityHandlerContext,
        make_runtime_observability_handlers,
        {
            "require_auth": require_auth,
            "record_request": _record_request,
            "cors_json_response": _cors_json_response,
            "metrics": BRIDGE_METRICS,
            "metrics_lock": _metrics_lock,
            "active_processes": ACTIVE_PROCESSES,
            "cdp_state": _cdp_state,
            "watchdog_state": _watchdog_state,
            "event_subscribers": _event_subscribers,
            "tls_config": _tls_config,
            "grpc_config": _grpc_config,
            "cluster_state": _cluster_state,
            "sandbox_config": _sandbox_config,
            "otel_config": _otel_config,
            "log_file": LOG_FILE,
            "version": VERSION,
            "now": time.time,
            "log_error": log.error,
        },
        {
            "handle_v1_metrics": "metrics",
            "handle_prometheus_metrics": "prometheus_metrics",
            "handle_v1_logs": "logs",
        },
    )
    registry.update(_runtime_observability_handler_registry)


    _tracing_handler_registry = build_context_handlers(
        TracingHandlerContext,
        make_tracing_handlers,
        {
            "require_auth": require_auth,
            "record_request": _record_request,
            "cors_json_response": _cors_json_response,
            "version": VERSION,
            "log_info": log.info,
        },
        {
            "handle_v1_tracing": "tracing",
            "handle_v1_traces_export": "traces_export",
        },
    )
    registry.update(_tracing_handler_registry)


    _user_handler_registry = build_context_handlers(
        UserHandlerContext,
        make_user_handlers,
        {
            "require_auth": require_auth,
            "record_request": _record_request,
            "cors_json_response": _cors_json_response,
            "check_auth_with_role": check_auth_with_role,
            "list_users": _user_store.list_users_for_response,
            "add_or_update_user": _user_store.add_or_update_user,
            "remove_user": _user_store.remove_user,
            "token_generator": b64_token,
            "audit": audit,
            "log_info": log.info,
        },
        {"handle_v1_users": "users"},
    )
    registry.update(_user_handler_registry)


    _file_handler_registry = build_context_handlers(
        FileHandlerContext,
        make_file_handlers,
        {
            "require_auth": require_auth,
            "record_request": _record_request,
            "cors_json_response": _cors_json_response,
            "audit": audit,
            "home": Path.home(),
            "bridge_py": Path(__file__).resolve(),
        },
        {
            "handle_v1_upload": "upload",
            "handle_v1_download": "download",
        },
    )
    registry.update(_file_handler_registry)
    return registry
