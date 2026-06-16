"""OpenTelemetry-style in-memory tracing helper and handler facade."""
from __future__ import annotations

from dataclasses import dataclass

from arena.handler_context import TracingHandlerContext
from arena.observability.tracing_config_handler import make_tracing_config_handler
from arena.observability.tracing_core import _otel_record_span, _otel_should_sample, _otel_trace_id
from arena.observability.tracing_export_handler import make_traces_export_handler
from arena.observability.tracing_state import _otel_config, _otel_lock, _otel_traces


@dataclass(frozen=True)
class TracingHandlers:
    tracing: object
    traces_export: object


def make_tracing_handlers(ctx: TracingHandlerContext) -> TracingHandlers:
    return TracingHandlers(
        tracing=make_tracing_config_handler(ctx),
        traces_export=make_traces_export_handler(ctx),
    )


__all__ = [
    "TracingHandlers",
    "_otel_config",
    "_otel_lock",
    "_otel_record_span",
    "_otel_should_sample",
    "_otel_trace_id",
    "_otel_traces",
    "make_tracing_handlers",
]
