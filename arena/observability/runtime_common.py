"""Shared helpers for runtime observability handlers."""
from __future__ import annotations

from datetime import datetime, timezone


def cluster_role_value(role: str) -> int:
    return 0 if role == "standalone" else 1 if role == "follower" else 2


def metrics_snapshot(ctx) -> dict:
    with ctx.metrics_lock:
        durations = ctx.metrics["request_durations"]
        avg_duration = round(sum(durations) / len(durations), 6) if durations else 0.0
        uptime = round(ctx.now() - ctx.metrics["start_time"], 1)
        error_rate = 0.0
        if ctx.metrics["total_requests"] > 0:
            error_rate = round(ctx.metrics["total_errors"] / ctx.metrics["total_requests"] * 100, 2)
        return {
            "uptime": uptime,
            "durations": list(durations),
            "avg_duration": avg_duration,
            "error_rate": error_rate,
            "start_time": datetime.fromtimestamp(ctx.metrics["start_time"], tz=timezone.utc).isoformat(),
            "total_requests": ctx.metrics["total_requests"],
            "total_exec": ctx.metrics["total_exec"],
            "total_errors": ctx.metrics["total_errors"],
        }


def duration_quantiles(durations: list[float]) -> tuple[float, float, float]:
    if not durations:
        return 0.0, 0.0, 0.0
    sorted_durations = sorted(durations)
    p50 = sorted_durations[len(sorted_durations) // 2]
    p95 = sorted_durations[int(len(sorted_durations) * 0.95)] if len(sorted_durations) >= 20 else sorted_durations[-1]
    p99 = sorted_durations[int(len(sorted_durations) * 0.99)] if len(sorted_durations) >= 100 else sorted_durations[-1]
    return p50, p95, p99
