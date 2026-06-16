# ruff: noqa: F821
"""Legacy ops handler registry wiring."""
from __future__ import annotations

from collections.abc import MutableMapping
from typing import Any, Callable


def build_legacy_ops_registries(g: MutableMapping[str, Any]) -> dict[str, Callable]:
    globals().update(g)
    registry: dict[str, Callable] = {}

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
    return registry
