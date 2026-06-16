"""Handlers for runtime metrics, Prometheus export and bridge log tailing."""
from __future__ import annotations

from dataclasses import dataclass

from aiohttp import web

from arena.handler_context import RuntimeObservabilityHandlerContext
from arena.observability.logs_handler import make_logs_handler
from arena.observability.metrics_handler import make_metrics_handler
from arena.observability.prometheus_handler import make_prometheus_metrics_handler
from arena.observability.runtime_common import cluster_role_value as _cluster_role_value


@dataclass(frozen=True)
class RuntimeObservabilityHandlers:
    metrics: object
    prometheus_metrics: object
    logs: object


def _as_runtime_handler(handler):
    """Preserve historical __module__ for compatibility diagnostics/tests."""
    try:
        handler.__module__ = __name__
    except Exception:
        pass
    return handler


def make_runtime_observability_handlers(ctx: RuntimeObservabilityHandlerContext) -> RuntimeObservabilityHandlers:
    return RuntimeObservabilityHandlers(
        metrics=_as_runtime_handler(make_metrics_handler(ctx)),
        prometheus_metrics=_as_runtime_handler(make_prometheus_metrics_handler(ctx)),
        logs=_as_runtime_handler(make_logs_handler(ctx)),
    )


__all__ = ["RuntimeObservabilityHandlers", "_cluster_role_value", "make_runtime_observability_handlers"]
