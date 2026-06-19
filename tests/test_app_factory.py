"""Arena app factory extraction tests."""
import asyncio
import sys
from pathlib import Path

from aiohttp import web

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import unified_bridge as ub  # noqa: E402
from arena.app import make_app as make_arena_app  # noqa: E402
from arena.app_keys import APP_CFG, APP_MCP_SESSIONS  # noqa: E402


def test_unified_make_app_uses_arena_app_factory():
    assert ub._make_arena_app is make_arena_app


def test_arena_app_factory_sets_cfg_ref_routes_and_lifecycle():
    refs = []

    async def startup(app):
        pass

    async def cleanup(app):
        pass

    app = make_arena_app(
        {"token": "test"},
        handlers=ub.__dict__,
        error_middleware=ub.error_middleware,
        on_startup=startup,
        on_cleanup=cleanup,
        set_app_ref=refs.append,
    )
    assert app[APP_CFG] == {"token": "test"}
    assert app[APP_MCP_SESSIONS] == {}
    assert refs == [app]
    paths = {(r.method, r.resource.get_info().get("path") or r.resource.get_info().get("formatter")) for r in app.router.routes()}
    assert ("GET", "/health") in paths
    assert ("POST", "/mcp") in paths
    assert startup in app.on_startup
    assert cleanup in app.on_cleanup


def test_unified_make_app_sets_app_ref():
    app = ub.make_app({
        "token": "test",
        "profile": "owner-shell",
        "root": Path("/tmp"),
        "active_exec": 0,
        "max_concurrent": 3,
        "audit": "audit",
        "timeout": 60,
        "max_timeout": 3600,
        "max_output": 2000000,
        "allow_any_cwd": False,
        "semaphore": asyncio.Semaphore(1),
    })
    assert ub._app_ref is app
