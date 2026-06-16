"""ops handler registry wiring."""
from __future__ import annotations

from collections.abc import MutableMapping
from typing import Any, Callable

from arena.wiring.env import RuntimeEnv


def build_ops_registries(g: MutableMapping[str, Any]) -> dict[str, Callable]:
    env = RuntimeEnv(g)
    registry: dict[str, Callable] = {}

    _alert_handler_registry = env.build_context_handlers(
        env.AlertsHandlerContext,
        env.make_alert_handlers,
        {
            "require_auth": env.require_auth,
            "record_request": env._record_request,
            "cors_json_response": env._cors_json_response,
            "metrics": env.BRIDGE_METRICS,
            "watchdog_state": env._watchdog_state,
            "cdp_state": env._cdp_state,
            "rate_limit_lock": env._rate_limit_lock,
            "rate_limit_store": env._rate_limit_store,
            "rate_limit_window": env._rate_limit_window,
            "rate_limit_max": env._rate_limit_max,
            "now": env.time.time,
            "log_info": env.log.info,
        },
        {"handle_v1_alerts": "alerts"},
    )
    registry.update(_alert_handler_registry)


    _rate_limit_handler_registry = env.build_context_handlers(
        env.RateLimitHandlerContext,
        env.make_rate_limit_handlers,
        {
            "require_auth": env.require_auth,
            "record_request": env._record_request,
            "cors_json_response": env._cors_json_response,
            "update_rate_limit_config": env.update_rate_limit_config,
            "rate_limit_stats": env.rate_limit_stats,
            "log_info": env.log.info,
        },
        {"handle_v1_ratelimit": "ratelimit"},
    )
    registry.update(_rate_limit_handler_registry)


    _tls_handler_registry = env.build_context_handlers(
        env.TlsHandlerContext,
        env.make_tls_handlers,
        {
            "require_auth": env.require_auth,
            "record_request": env._record_request,
            "cors_json_response": env._cors_json_response,
            "generate_self_signed_cert": env._generate_self_signed_cert,
            "get_tailscale_cert": env._get_tailscale_cert,
            "log_info": env.log.info,
        },
        {"handle_v1_tls": "tls"},
    )
    registry.update(_tls_handler_registry)


    _sandbox_handler_registry = env.build_context_handlers(
        env.SandboxHandlerContext,
        env.make_sandbox_handlers,
        {
            "require_auth": env.require_auth,
            "record_request": env._record_request,
            "cors_json_response": env._cors_json_response,
            "blocked_reason": env.blocked_reason,
            "first_word": env.first_word,
            "run_sandboxed": env._run_sandboxed,
            "audit": env.audit,
            "emit_event": env.emit_event,
        },
        {"handle_v1_sandbox": "sandbox"},
    )
    registry.update(_sandbox_handler_registry)


    _cluster_handler_registry = env.build_context_handlers(
        env.ClusterHandlerContext,
        env.make_cluster_handlers,
        {
            "require_auth": env.require_auth,
            "record_request": env._record_request,
            "cors_json_response": env._cors_json_response,
            "get_node_id": env._get_node_id,
            "start_heartbeat": lambda: env.start_cluster_heartbeat(log_error=env.log.error),
            "stop_heartbeat": env.stop_cluster_heartbeat,
            "audit": env.audit,
            "log_info": env.log.info,
        },
        {"handle_v1_cluster": "cluster"},
    )
    registry.update(_cluster_handler_registry)
    return registry
