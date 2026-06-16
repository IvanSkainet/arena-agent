"""Handlers for the v2 compatibility API endpoints."""
from __future__ import annotations

from dataclasses import dataclass

from arena.api_v2.common import cfg_get_max_timeout, tls_ready as _tls_ready
from arena.api_v2.constants import DEPRECATED_ENDPOINTS
from arena.api_v2.exec_handler import make_v2_exec_handler
from arena.api_v2.info_handlers import (
    make_v2_browser_status_handler,
    make_v2_deprecations_handler,
    make_v2_health_handler,
    make_v2_index_handler,
    make_v2_status_handler,
)
from arena.handler_context import ApiV2HandlerContext


@dataclass(frozen=True)
class V2Handlers:
    index: object
    status: object
    health: object
    browser_status: object
    exec: object
    deprecations: object


def make_v2_handlers(ctx: ApiV2HandlerContext) -> V2Handlers:
    return V2Handlers(
        index=make_v2_index_handler(ctx),
        status=make_v2_status_handler(ctx),
        health=make_v2_health_handler(ctx),
        browser_status=make_v2_browser_status_handler(ctx),
        exec=make_v2_exec_handler(ctx),
        deprecations=make_v2_deprecations_handler(ctx),
    )


__all__ = ["DEPRECATED_ENDPOINTS", "V2Handlers", "_tls_ready", "cfg_get_max_timeout", "make_v2_handlers"]
