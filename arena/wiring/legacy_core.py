"""Legacy core handler registry wiring."""
from __future__ import annotations

from collections.abc import MutableMapping
from typing import Any, Callable

from arena.wiring.env import RuntimeEnv


def build_legacy_core_registries(g: MutableMapping[str, Any]) -> dict[str, Callable]:
    env = RuntimeEnv(g)
    registry: dict[str, Callable] = {}

    _gateway_handler_registry = env.build_context_handlers(
        env.GatewayHandlerContext,
        env.make_gateway_handlers,
        {
            "require_auth": env.require_auth,
            "record_request": env._record_request,
            "cors_json_response": env._cors_json_response,
            "executor": env._EXECUTOR,
            "handle_rpc": env.handle_rpc,
            "subprocess_kwargs": env._subprocess_kwargs,
        },
        {
            "handle_gateway_index": "index",
            "handle_gateway_tools": "tools",
            "handle_gateway_run": "run",
            "handle_gateway_tool": "tool",
        },
    )
    registry.update(_gateway_handler_registry)


    _mcp_handler_registry = env.build_context_handlers(
        env.McpHandlerContext,
        env.make_mcp_handlers,
        {
            "require_auth": env.require_auth,
            "record_request": env._record_request,
            "cors_json_response": env._cors_json_response,
            "handle_rpc": env.handle_rpc,
            "log_error": env.log.error,
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


    _api_v2_handler_registry = env.build_context_handlers(
        env.ApiV2HandlerContext,
        env.make_v2_handlers,
        {
            "require_auth": env.require_auth,
            "record_request": env._record_request,
            "cors_json_response": env._cors_json_response,
            "version": env.VERSION,
            "metrics": env.BRIDGE_METRICS,
            "cdp_state": env._cdp_state,
            "watchdog_state": env._watchdog_state,
            "cluster_state": env._cluster_state,
            "cluster_config": env._cluster_config,
            "tls_config": env._tls_config,
            "profiles_dir": env._PROFILES_DIR,
            "sandbox_config": env._sandbox_config,
            "blocked_reason": env.blocked_reason,
            "first_word": env.first_word,
            "decode_output": env.decode_output,
            "run_sandboxed": env._run_sandboxed,
            "cfg_get_max_timeout": env.cfg_get_max_timeout,
            "audit": env.audit,
            "emit_event": env.emit_event,
            "now": env.time.time,
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


    _batch_handler_registry = env.build_context_handlers(
        env.BatchHandlerContext,
        env.make_batch_handlers,
        {
            "require_auth": env.require_auth,
            "record_request": env._record_request,
            "cors_json_response": env._cors_json_response,
            "emit_event": env.emit_event,
            "now": env.time.time,
        },
        {"handle_v1_batch": "batch"},
    )
    registry.update(_batch_handler_registry)
    return registry
