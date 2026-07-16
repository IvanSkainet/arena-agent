"""Handlers for runtime metrics, Prometheus export and bridge log tailing."""
from __future__ import annotations

from dataclasses import dataclass

from aiohttp import web

from arena.handler_context import RuntimeObservabilityHandlerContext
from arena.observability.live_metrics_handler import make_live_metrics_handlers
from arena.observability.logs_handler import make_logs_handler
from arena.observability.metrics_handler import make_metrics_handler
from arena.observability.prometheus_handler import make_prometheus_metrics_handler
from arena.observability.runtime_common import cluster_role_value as _cluster_role_value


@dataclass(frozen=True)
class RuntimeObservabilityHandlers:
    metrics: object
    prometheus_metrics: object
    logs: object
    # v3.95.0 -- live-metrics for Dashboard sparkline charts.
    live_metrics: object
    live_metrics_stream: object


def _as_runtime_handler(handler):
    """Preserve historical __module__ for compatibility diagnostics/tests."""
    try:
        handler.__module__ = __name__
    except Exception:
        pass
    return handler


def make_runtime_observability_handlers(ctx: RuntimeObservabilityHandlerContext) -> RuntimeObservabilityHandlers:
    live = make_live_metrics_handlers(ctx)
    return RuntimeObservabilityHandlers(
        metrics=_as_runtime_handler(make_metrics_handler(ctx)),
        prometheus_metrics=_as_runtime_handler(make_prometheus_metrics_handler(ctx)),
        logs=_as_runtime_handler(make_logs_handler(ctx)),
        live_metrics=_as_runtime_handler(live["live_metrics"]),
        live_metrics_stream=_as_runtime_handler(live["live_metrics_stream"]),
    )


__all__ = ["RuntimeObservabilityHandlers", "_cluster_role_value", "make_runtime_observability_handlers"]
