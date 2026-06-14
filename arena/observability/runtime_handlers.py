"""Handlers for runtime metrics, Prometheus export and bridge log tailing."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from aiohttp import web

from arena.handler_context import RuntimeObservabilityHandlerContext


@dataclass(frozen=True)
class RuntimeObservabilityHandlers:
    metrics: object
    prometheus_metrics: object
    logs: object


def _cluster_role_value(role: str) -> int:
    return 0 if role == "standalone" else 1 if role == "follower" else 2


def make_runtime_observability_handlers(ctx: RuntimeObservabilityHandlerContext) -> RuntimeObservabilityHandlers:
    async def handle_v1_metrics(request: web.Request) -> web.Response:
        """GET /v1/metrics — Bridge performance metrics."""
        try:
            ctx.record_request()
            with ctx.metrics_lock:
                durations = ctx.metrics["request_durations"]
                avg_duration = round(sum(durations) / len(durations), 6) if durations else 0.0
                uptime = round(ctx.now() - ctx.metrics["start_time"], 1)
                error_rate = 0.0
                if ctx.metrics["total_requests"] > 0:
                    error_rate = round(ctx.metrics["total_errors"] / ctx.metrics["total_requests"] * 100, 2)

                result = {
                    "ok": True,
                    "uptime_seconds": uptime,
                    "total_requests": ctx.metrics["total_requests"],
                    "total_exec": ctx.metrics["total_exec"],
                    "total_errors": ctx.metrics["total_errors"],
                    "average_duration_sec": avg_duration,
                    "error_rate_percent": error_rate,
                    "start_time": datetime.fromtimestamp(ctx.metrics["start_time"], tz=timezone.utc).isoformat(),
                    "version": ctx.version,
                    "active_processes": len(ctx.active_processes),
                }
            return ctx.cors_json_response(result)
        except Exception as e:
            return ctx.cors_json_response({"ok": False, "error": str(e)}, status=500)

    async def handle_prometheus_metrics(request: web.Request) -> web.Response:
        """GET /metrics — Prometheus-compatible metrics endpoint.

        No auth required — this is standard for /metrics endpoints (scraped by Prometheus).
        """
        try:
            with ctx.metrics_lock:
                uptime = round(ctx.now() - ctx.metrics["start_time"], 1)
                durations = list(ctx.metrics["request_durations"])
                avg_duration = round(sum(durations) / len(durations), 6) if durations else 0.0

            # Calculate quantiles outside the lock to avoid holding it too long.
            if durations:
                sd = sorted(durations)
                p50 = sd[len(sd)//2]
                p95 = sd[int(len(sd)*0.95)] if len(sd) >= 20 else sd[-1]
                p99 = sd[int(len(sd)*0.99)] if len(sd) >= 100 else sd[-1]
            else:
                p50 = p95 = p99 = 0.0

            lines = [
                "# HELP arena_bridge_uptime_seconds Bridge uptime in seconds",
                "# TYPE arena_bridge_uptime_seconds gauge",
                f"arena_bridge_uptime_seconds {uptime}",
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
                f"arena_bridge_request_duration_avg_seconds {avg_duration}",
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
                f"arena_bridge_cluster_role {{'role': '{ctx.cluster_state['role']}'}} {_cluster_role_value(ctx.cluster_state['role'])}",
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

            return web.Response(text="\n".join(lines), content_type="text/plain; version=0.0.4", charset="utf-8")
        except Exception:
            return web.Response(text="# ERROR: internal error\n", status=500, content_type="text/plain", charset="utf-8")

    async def handle_v1_logs(request: web.Request) -> web.Response:
        """Return recent bridge log entries with optional level filter."""
        r = ctx.require_auth(request)
        if r:
            return r
        ctx.record_request()
        try:
            level = request.query.get("level", "INFO").upper()
            lines_count = min(int(request.query.get("lines", "100")), 1000)
        except (ValueError, TypeError):
            level = "INFO"
            lines_count = 100

        valid_levels = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
        if level not in valid_levels:
            level = "INFO"

        log_entries: list[str] = []
        try:
            if ctx.log_file.exists():
                text = ctx.log_file.read_text(encoding="utf-8", errors="replace")
                all_lines = text.splitlines()
                min_idx = valid_levels.index(level) if level in valid_levels else 1
                filter_levels = valid_levels[min_idx:]
                for line in all_lines:
                    if any(f" {lv} " in line for lv in filter_levels):
                        log_entries.append(line)
                log_entries = log_entries[-lines_count:]
        except Exception as e:
            ctx.log_error("Failed to read log file: %s", e)

        return ctx.cors_json_response({
            "ok": True,
            "log_file": str(ctx.log_file),
            "level_filter": level,
            "lines": len(log_entries),
            "entries": log_entries,
        })

    return RuntimeObservabilityHandlers(
        metrics=handle_v1_metrics,
        prometheus_metrics=handle_prometheus_metrics,
        logs=handle_v1_logs,
    )
