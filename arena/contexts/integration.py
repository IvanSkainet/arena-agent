"""Handler context dataclasses for integration domains."""
from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import Executor
from dataclasses import dataclass
from typing import Any

from aiohttp import web


@dataclass(frozen=True)
class BatchHandlerContext:
    """Dependencies for batch operation handlers."""

    require_auth: Callable[[web.Request], web.Response | None]
    record_request: Callable[..., None]
    cors_json_response: Callable[..., web.Response]
    emit_event: Callable[[str, dict | None], Any]
    now: Callable[[], float]


@dataclass(frozen=True)
class TlsHandlerContext:
    """Dependencies for TLS configuration handlers."""

    require_auth: Callable[[web.Request], web.Response | None]
    record_request: Callable[..., None]
    cors_json_response: Callable[..., web.Response]
    generate_self_signed_cert: Callable[[], tuple[str, str]]
    get_tailscale_cert: Callable[[], tuple[str, str]]
    log_info: Callable[..., None]


@dataclass(frozen=True)
class SandboxHandlerContext:
    """Dependencies for sandbox execution/configuration handlers."""

    require_auth: Callable[[web.Request], web.Response | None]
    record_request: Callable[..., None]
    cors_json_response: Callable[..., web.Response]
    blocked_reason: Callable[[str], str | None]
    first_word: Callable[[str], str]
    run_sandboxed: Callable[..., Any]
    audit: Callable[[dict[str, Any]], None]
    emit_event: Callable[[str, dict | None], Any]


@dataclass(frozen=True)
class ClusterHandlerContext:
    """Dependencies for cluster/high-availability handlers."""

    require_auth: Callable[[web.Request], web.Response | None]
    record_request: Callable[..., None]
    cors_json_response: Callable[..., web.Response]
    get_node_id: Callable[[], str]
    start_heartbeat: Callable[[], Any]
    stop_heartbeat: Callable[[], Any]
    audit: Callable[[dict[str, Any]], None]
    log_info: Callable[..., None]


@dataclass(frozen=True)
class GrpcHandlerContext:
    """Dependencies for gRPC-style secondary interface handlers."""

    require_auth: Callable[[web.Request], web.Response | None]
    record_request: Callable[..., None]
    cors_json_response: Callable[..., web.Response]
    server_task: Callable[[], Any]
    start_server: Callable[[dict[str, Any]], Any]
    stop_server: Callable[[], Any]


@dataclass(frozen=True)
class ExtensionBridgeHandlerContext:
    """Dependencies for browser chat extension bridge handlers."""

    require_auth: Callable[[web.Request], web.Response | None]
    record_request: Callable[..., None]
    cors_json_response: Callable[..., web.Response]
    executor: Executor
    policies_sync: Callable[[dict[str, Any] | None], dict[str, Any]]
    preview_sync: Callable[[dict[str, Any]], dict[str, Any]]
    execute_sync: Callable[[dict[str, Any]], dict[str, Any]]
    instructions_sync: Callable[[dict[str, Any] | None], dict[str, Any]]


@dataclass(frozen=True)
class EventHandlerContext:
    """Dependencies for realtime event WebSocket handlers."""

    require_auth: Callable[[web.Request], web.Response | None]
    version: str
    utc_now: Callable[[], str]
    log_info: Callable[..., None]


@dataclass(frozen=True)
class FileWatchHandlerContext:
    """Dependencies for file watcher management handlers."""

    require_auth: Callable[[web.Request], web.Response | None]
    record_request: Callable[..., None]
    cors_json_response: Callable[..., web.Response]
    app_cfg_key: Any
    home: Any
    list_sync: Callable[[], dict[str, Any]]
    add_sync: Callable[..., dict[str, Any]]
    remove_sync: Callable[[str], dict[str, Any]]
    utc_now: Callable[[], str]


@dataclass(frozen=True)
class WatchdogHandlerContext:
    """Dependencies for watchdog status/config handlers."""

    require_auth: Callable[[web.Request], web.Response | None]
    record_request: Callable[..., None]
    cors_json_response: Callable[..., web.Response]
    metrics: dict[str, Any]
    now: Callable[[], float]
    log_info: Callable[..., None]


@dataclass(frozen=True)
class McpHandlerContext:
    """Dependencies for MCP HTTP/SSE/WebSocket transport handlers."""

    require_auth: Callable[[web.Request], web.Response | None]
    record_request: Callable[..., None]
    cors_json_response: Callable[..., web.Response]
    handle_rpc: Callable[[dict[str, Any]], dict[str, Any] | None]
    log_error: Callable[..., None]

__all__ = ['BatchHandlerContext', 'TlsHandlerContext', 'SandboxHandlerContext', 'ClusterHandlerContext', 'GrpcHandlerContext', 'ExtensionBridgeHandlerContext', 'EventHandlerContext', 'FileWatchHandlerContext', 'WatchdogHandlerContext', 'McpHandlerContext']
