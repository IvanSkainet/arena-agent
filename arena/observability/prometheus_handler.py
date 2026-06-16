"""Prometheus metrics handler."""
from __future__ import annotations

from aiohttp import web

from arena.handler_context import RuntimeObservabilityHandlerContext
from arena.observability.runtime_common import cluster_role_value, duration_quantiles, metrics_snapshot


def _prometheus_lines(ctx: RuntimeObservabilityHandlerContext, snap: dict) -> list[str]:
    p50, p95, p99 = duration_quantiles(snap["durations"])
    return [
        "# HELP arena_bridge_uptime_seconds Bridge uptime in seconds",
        "# TYPE arena_bridge_uptime_seconds gauge",
        f"arena_bridge_uptime_seconds {snap['uptime']}",
        "",
        "# HELP arena_bridge_requests_total Total number of requests",
        "# TYPE arena_bridge_requests_total counter",
        f"arena_bridge_requests_total {ctx.metrics['total_requests']}",
        "",
        "# HELP arena_bridge_exec_total Total number of exec operations",
        "# TYPE arena_bridge_exec_total counter",
        f"arena_bridge_exec_total {ctx.metrics['total_exec']}",
        "",
        "# HELP arena_bridge_errors_total Total number of errors",
        "# TYPE arena_bridge_errors_total counter",
        f"arena_bridge_errors_total {ctx.metrics['total_errors']}",
        "",
        "# HELP arena_bridge_request_duration_avg_seconds Average request duration",
        "# TYPE arena_bridge_request_duration_avg_seconds gauge",
        f"arena_bridge_request_duration_avg_seconds {snap['avg_duration']}",
        "",
        "# HELP arena_bridge_request_duration_seconds Request duration quantiles",
        "# TYPE arena_bridge_request_duration_seconds summary",
        f'arena_bridge_request_duration_seconds{{quantile="0.5"}} {p50}',
        f'arena_bridge_request_duration_seconds{{quantile="0.95"}} {p95}',
        f'arena_bridge_request_duration_seconds{{quantile="0.99"}} {p99}',
        "",
        "# HELP arena_bridge_active_processes Number of active subprocesses",
        "# TYPE arena_bridge_active_processes gauge",
        f"arena_bridge_active_processes {len(ctx.active_processes)}",
        "",
        "# HELP arena_bridge_cdp_connected CDP connection status (1=connected, 0=disconnected)",
        "# TYPE arena_bridge_cdp_connected gauge",
        f"arena_bridge_cdp_connected {1 if ctx.cdp_state['connected'] else 0}",
        "",
        "# HELP arena_bridge_cdp_reconnect_count Total number of CDP auto-reconnects",
        "# TYPE arena_bridge_cdp_reconnect_count counter",
        f"arena_bridge_cdp_reconnect_count {ctx.cdp_state.get('reconnect_count', 0)}",
        "",
        "# HELP arena_bridge_info Bridge version info",
        "# TYPE arena_bridge_info gauge",
        f'arena_bridge_info{{version="{ctx.version}"}} 1',
        "",
        "# HELP arena_bridge_memory_mb Bridge memory usage in MB",
        "# TYPE arena_bridge_memory_mb gauge",
        f"arena_bridge_memory_mb {ctx.watchdog_state['memory_mb']}",
        "",
        "# HELP arena_bridge_cpu_percent Bridge CPU usage percent",
        "# TYPE arena_bridge_cpu_percent gauge",
        f"arena_bridge_cpu_percent {ctx.watchdog_state['cpu_percent']}",
        "",
        "# HELP arena_bridge_event_subscribers Number of event stream subscribers",
        "# TYPE arena_bridge_event_subscribers gauge",
        f"arena_bridge_event_subscribers {len(ctx.event_subscribers)}",
        "",
        "# HELP arena_bridge_tls_enabled TLS/HTTPS enabled status",
        "# TYPE arena_bridge_tls_enabled gauge",
        f"arena_bridge_tls_enabled {1 if ctx.tls_config['enabled'] else 0}",
        "",
        "# HELP arena_bridge_grpc_enabled gRPC secondary interface enabled",
        "# TYPE arena_bridge_grpc_enabled gauge",
        f"arena_bridge_grpc_enabled {1 if ctx.grpc_config['enabled'] else 0}",
        "",
        "# HELP arena_bridge_cluster_role Cluster role (0=standalone, 1=follower, 2=leader)",
        "# TYPE arena_bridge_cluster_role gauge",
        f"arena_bridge_cluster_role {{'role': '{ctx.cluster_state['role']}'}} {cluster_role_value(ctx.cluster_state['role'])}",
        "",
        "# HELP arena_bridge_sandbox_enabled Skill sandbox enabled",
        "# TYPE arena_bridge_sandbox_enabled gauge",
        f"arena_bridge_sandbox_enabled {1 if ctx.sandbox_config['enabled'] else 0}",
        "",
        "# HELP arena_bridge_otel_enabled OpenTelemetry tracing enabled",
        "# TYPE arena_bridge_otel_enabled gauge",
        f"arena_bridge_otel_enabled {1 if ctx.otel_config['enabled'] else 0}",
        "",
    ]


def make_prometheus_metrics_handler(ctx: RuntimeObservabilityHandlerContext):
    async def handle_prometheus_metrics(request: web.Request) -> web.Response:
        """GET /metrics — Prometheus-compatible metrics endpoint."""
        try:
            snap = metrics_snapshot(ctx)
            return web.Response(text="\n".join(_prometheus_lines(ctx, snap)), content_type="text/plain; version=0.0.4", charset="utf-8")
        except Exception:
            return web.Response(text="# ERROR: internal error\n", status=500, content_type="text/plain", charset="utf-8")

    return handle_prometheus_metrics
