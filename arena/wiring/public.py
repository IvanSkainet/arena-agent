"""Public route handler wiring."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class PublicWiringContext:
    record_request: Callable[..., None]
    cors_json_response: Callable[..., Any]
    metrics: dict[str, Any]
    version: str
    now: Callable[[], float]
    hostname: Callable[[], str]
    bridge_port: Callable[[], int]


def build_public_handlers(ctx: PublicWiringContext) -> dict[str, Callable[..., Any]]:
    """Build public/index/health/API-doc handlers for the route registry."""
    from arena.handler_context import PublicHandlerContext
    from arena.public.handlers import make_public_handlers

    public_ctx = PublicHandlerContext(
        record_request=ctx.record_request,
        cors_json_response=ctx.cors_json_response,
        metrics=ctx.metrics,
        version=ctx.version,
        now=ctx.now,
        hostname=ctx.hostname,
        bridge_port=ctx.bridge_port,
    )
    handlers = make_public_handlers(public_ctx)
    return {
        "handle_index": handlers.index,
        "handle_health": handlers.health,
        "handle_api_docs": handlers.api_docs,
    }
