"""Route registration facade for the unified bridge app."""
from __future__ import annotations

from collections.abc import Callable, Mapping

from aiohttp import web

from arena.route_registry.cdp import register_cdp_routes
from arena.route_registry.compat import register_compat_routes
from arena.route_registry.core import register_core_routes
from arena.route_registry.desktop import register_desktop_routes
from arena.route_registry.domain import register_domain_routes


def register_routes(app: web.Application, h: Mapping[str, Callable]) -> None:
    """Register all public API routes without changing route names/paths.

    ``h`` is intentionally a mapping of legacy handler globals at this migration
    stage. A typed HandlerRegistry can replace it once the composition root is
    fully split out of unified_bridge.py.
    """
    register_core_routes(app, h)
    register_cdp_routes(app, h)
    register_desktop_routes(app, h)
    register_domain_routes(app, h)
    register_compat_routes(app, h)


__all__ = ["register_routes"]
