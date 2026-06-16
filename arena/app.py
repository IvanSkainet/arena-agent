"""Application factory for the Arena unified bridge."""
from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from aiohttp import web

from arena.routes import register_routes


def make_app(
    cfg: dict[str, Any],
    *,
    handlers: Mapping[str, Callable],
    error_middleware: Callable,
    on_startup: Callable[[web.Application], Any],
    on_cleanup: Callable[[web.Application], Any],
    set_app_ref: Callable[[web.Application], None] | None = None,
    client_max_size: int = 50 * 1024 * 1024,
) -> web.Application:
    """Create and wire the aiohttp application.

    The handler mapping is intentionally the global-handler mapping during
    the v3 migration. Once the container is fully typed, this can accept a
    HandlerRegistry instead without changing route registration.
    """
    app = web.Application(client_max_size=client_max_size, middlewares=[error_middleware])
    app["cfg"] = cfg
    app["mcp_sessions"] = {}

    if set_app_ref is not None:
        set_app_ref(app)

    register_routes(app, handlers)

    app.on_startup.append(on_startup)
    app.on_cleanup.append(on_cleanup)

    return app
