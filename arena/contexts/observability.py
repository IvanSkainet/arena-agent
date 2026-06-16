"""Handler context dataclasses for observability domains."""
from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import Executor
from dataclasses import dataclass
from typing import Any

from aiohttp import web


@dataclass(frozen=True)
class ObservabilityHandlerContext:
    """Dependencies for audit/request-log/webhook handlers."""

    require_auth: Callable[[web.Request], web.Response | None]
    record_request: Callable[..., None]
    cors_json_response: Callable[..., web.Response]
    executor: Executor
    audit_path: Any
    request_log_file: Any
    read_tail: Callable[..., list[str]]
    read_request_log: Callable[..., list[dict[str, Any]]]
    audit_stats_sync: Callable[[], dict[str, Any]]
    load_webhooks: Callable[[], dict[str, Any]]
    save_webhooks: Callable[[dict[str, Any]], None]
    normalize_webhooks_config: Callable[[dict[str, Any]], tuple[dict[str, Any] | None, str | None]]
    audit: Callable[[dict[str, Any]], None]


@dataclass(frozen=True)
class TracingHandlerContext:
    """Dependencies for OpenTelemetry tracing handlers."""

    require_auth: Callable[[web.Request], web.Response | None]
    record_request: Callable[..., None]
    cors_json_response: Callable[..., web.Response]
    version: str
    log_info: Callable[..., None]


@dataclass(frozen=True)
class ApiV2HandlerContext:
    """Dependencies for v2 compatibility API handlers."""

    require_auth: Callable[[web.Request], web.Response | None]
    record_request: Callable[..., None]
    cors_json_response: Callable[..., web.Response]
    version: str
    metrics: dict[str, Any]
    cdp_state: dict[str, Any]
    watchdog_state: dict[str, Any]
    cluster_state: dict[str, Any]
    cluster_config: dict[str, Any]
    tls_config: dict[str, Any]
    profiles_dir: Any
    sandbox_config: dict[str, Any]
    blocked_reason: Callable[[str], str | None]
    first_word: Callable[[str], str]
    decode_output: Callable[[bytes], str]
    run_sandboxed: Callable[..., Any]
    cfg_get_max_timeout: Callable[[web.Request], int]
    audit: Callable[[dict[str, Any]], None]
    emit_event: Callable[[str, dict | None], Any]
    now: Callable[[], float]


@dataclass(frozen=True)
class AlertsHandlerContext:
    """Dependencies for alert configuration/status handlers."""

    require_auth: Callable[[web.Request], web.Response | None]
    record_request: Callable[..., None]
    cors_json_response: Callable[..., web.Response]
    metrics: dict[str, Any]
    watchdog_state: dict[str, Any]
    cdp_state: dict[str, Any]
    rate_limit_lock: Any
    rate_limit_store: dict[str, list[float]]
    rate_limit_window: float
    rate_limit_max: int
    now: Callable[[], float]
    log_info: Callable[..., None]


@dataclass(frozen=True)
class RateLimitHandlerContext:
    """Dependencies for rate-limit config/stat handlers."""

    require_auth: Callable[[web.Request], web.Response | None]
    record_request: Callable[..., None]
    cors_json_response: Callable[..., web.Response]
    update_rate_limit_config: Callable[[dict[str, Any]], None]
    rate_limit_stats: Callable[[], dict[str, Any]]
    log_info: Callable[..., None]


@dataclass(frozen=True)
class RuntimeObservabilityHandlerContext:
    """Dependencies for runtime metrics, Prometheus and bridge log handlers."""

    require_auth: Callable[[web.Request], web.Response | None]
    record_request: Callable[..., None]
    cors_json_response: Callable[..., web.Response]
    metrics: dict[str, Any]
    metrics_lock: Any
    active_processes: dict[str, dict[str, Any]]
    cdp_state: dict[str, Any]
    watchdog_state: dict[str, Any]
    event_subscribers: list[Any]
    tls_config: dict[str, Any]
    grpc_config: dict[str, Any]
    cluster_state: dict[str, Any]
    sandbox_config: dict[str, Any]
    otel_config: dict[str, Any]
    log_file: Any
    version: str
    now: Callable[[], float]
    log_error: Callable[..., None]

__all__ = ['ObservabilityHandlerContext', 'TracingHandlerContext', 'ApiV2HandlerContext', 'AlertsHandlerContext', 'RateLimitHandlerContext', 'RuntimeObservabilityHandlerContext']
