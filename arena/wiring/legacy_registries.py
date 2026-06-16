"""Legacy handler registry wiring extracted from unified_bridge.py.

This module intentionally consumes the compatibility globals mapping while the
bridge entrypoint is being reduced.  It keeps the old handler names stable while
moving large registry-construction blocks out of ``unified_bridge.py``.
"""
from __future__ import annotations

from collections.abc import MutableMapping
from typing import Any, Callable


def build_early_handler_registries(g: MutableMapping[str, Any]) -> dict[str, Callable]:
    """Build handler registries that only depend on already-initialized runtime state."""
    globals().update(g)
    registry: dict[str, Callable] = {}

    _gateway_handler_registry = build_context_handlers(
        GatewayHandlerContext,
        make_gateway_handlers,
        {
            "require_auth": require_auth,
            "record_request": _record_request,
            "cors_json_response": _cors_json_response,
            "executor": _EXECUTOR,
            "handle_rpc": handle_rpc,
            "subprocess_kwargs": _subprocess_kwargs,
        },
        {
            "handle_gateway_index": "index",
            "handle_gateway_tools": "tools",
            "handle_gateway_run": "run",
            "handle_gateway_tool": "tool",
        },
    )
    registry.update(_gateway_handler_registry)


    _mcp_handler_registry = build_context_handlers(
        McpHandlerContext,
        make_mcp_handlers,
        {
            "require_auth": require_auth,
            "record_request": _record_request,
            "cors_json_response": _cors_json_response,
            "handle_rpc": handle_rpc,
            "log_error": log.error,
        },
        {
            "handle_mcp_post": "mcp_post",
            "handle_mcp_delete": "mcp_delete",
            "handle_sse": "sse",
            "handle_sse_messages": "sse_messages",
            "handle_ws": "ws",
        },
    )
    registry.update(_mcp_handler_registry)


    _api_v2_handler_registry = build_context_handlers(
        ApiV2HandlerContext,
        make_v2_handlers,
        {
            "require_auth": require_auth,
            "record_request": _record_request,
            "cors_json_response": _cors_json_response,
            "version": VERSION,
            "metrics": BRIDGE_METRICS,
            "cdp_state": _cdp_state,
            "watchdog_state": _watchdog_state,
            "cluster_state": _cluster_state,
            "cluster_config": _cluster_config,
            "tls_config": _tls_config,
            "profiles_dir": _PROFILES_DIR,
            "sandbox_config": _sandbox_config,
            "blocked_reason": blocked_reason,
            "first_word": first_word,
            "decode_output": decode_output,
            "run_sandboxed": _run_sandboxed,
            "cfg_get_max_timeout": cfg_get_max_timeout,
            "audit": audit,
            "emit_event": emit_event,
            "now": time.time,
        },
        {
            "handle_v2_index": "index",
            "handle_v2_status": "status",
            "handle_v2_health": "health",
            "handle_v2_browser_status": "browser_status",
            "handle_v2_exec": "exec",
            "handle_v2_deprecations": "deprecations",
        },
    )
    registry.update(_api_v2_handler_registry)


    _batch_handler_registry = build_context_handlers(
        BatchHandlerContext,
        make_batch_handlers,
        {
            "require_auth": require_auth,
            "record_request": _record_request,
            "cors_json_response": _cors_json_response,
            "emit_event": emit_event,
            "now": time.time,
        },
        {"handle_v1_batch": "batch"},
    )
    registry.update(_batch_handler_registry)


    _alert_handler_registry = build_context_handlers(
        AlertsHandlerContext,
        make_alert_handlers,
        {
            "require_auth": require_auth,
            "record_request": _record_request,
            "cors_json_response": _cors_json_response,
            "metrics": BRIDGE_METRICS,
            "watchdog_state": _watchdog_state,
            "cdp_state": _cdp_state,
            "rate_limit_lock": _rate_limit_lock,
            "rate_limit_store": _rate_limit_store,
            "rate_limit_window": _rate_limit_window,
            "rate_limit_max": _rate_limit_max,
            "now": time.time,
            "log_info": log.info,
        },
        {"handle_v1_alerts": "alerts"},
    )
    registry.update(_alert_handler_registry)


    _rate_limit_handler_registry = build_context_handlers(
        RateLimitHandlerContext,
        make_rate_limit_handlers,
        {
            "require_auth": require_auth,
            "record_request": _record_request,
            "cors_json_response": _cors_json_response,
            "update_rate_limit_config": update_rate_limit_config,
            "rate_limit_stats": rate_limit_stats,
            "log_info": log.info,
        },
        {"handle_v1_ratelimit": "ratelimit"},
    )
    registry.update(_rate_limit_handler_registry)


    _tls_handler_registry = build_context_handlers(
        TlsHandlerContext,
        make_tls_handlers,
        {
            "require_auth": require_auth,
            "record_request": _record_request,
            "cors_json_response": _cors_json_response,
            "generate_self_signed_cert": _generate_self_signed_cert,
            "get_tailscale_cert": _get_tailscale_cert,
            "log_info": log.info,
        },
        {"handle_v1_tls": "tls"},
    )
    registry.update(_tls_handler_registry)


    _sandbox_handler_registry = build_context_handlers(
        SandboxHandlerContext,
        make_sandbox_handlers,
        {
            "require_auth": require_auth,
            "record_request": _record_request,
            "cors_json_response": _cors_json_response,
            "blocked_reason": blocked_reason,
            "first_word": first_word,
            "run_sandboxed": _run_sandboxed,
            "audit": audit,
            "emit_event": emit_event,
        },
        {"handle_v1_sandbox": "sandbox"},
    )
    registry.update(_sandbox_handler_registry)


    _cluster_handler_registry = build_context_handlers(
        ClusterHandlerContext,
        make_cluster_handlers,
        {
            "require_auth": require_auth,
            "record_request": _record_request,
            "cors_json_response": _cors_json_response,
            "get_node_id": _get_node_id,
            "start_heartbeat": lambda: start_cluster_heartbeat(log_error=log.error),
            "stop_heartbeat": stop_cluster_heartbeat,
            "audit": audit,
            "log_info": log.info,
        },
        {"handle_v1_cluster": "cluster"},
    )
    registry.update(_cluster_handler_registry)


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
        },
    )
    registry.update(_gui_handler_registry)


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
