# ruff: noqa: F821
"""Legacy core handler registry wiring."""
from __future__ import annotations

from collections.abc import MutableMapping
from typing import Any, Callable


def build_legacy_core_registries(g: MutableMapping[str, Any]) -> dict[str, Callable]:
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
    return registry
