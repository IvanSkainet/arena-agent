"""Tests for /v1/agent/config (v4.1.0)."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def test_agent_config_route_registered_in_registry():
    from arena.route_registry.registry import ROUTES
    keys = {(m, p) for (m, p, *_rest) in ROUTES}
    assert ("GET", "/v1/agent/config") in keys


def test_agent_config_route_wired_into_app():
    import unified_bridge as ub
    app = ub.make_app({
        "token": "test", "profile": "owner-shell", "root": Path("/tmp"),
        "active_exec": 0, "max_concurrent": 3, "audit": "audit",
        "timeout": 60, "max_timeout": 3600, "max_output": 2000000,
        "allow_any_cwd": False, "semaphore": asyncio.Semaphore(1),
    })
    paths = {
        (r.method, r.resource.get_info().get("path") or r.resource.get_info().get("formatter"))
        for r in app.router.routes()
    }
    assert ("GET", "/v1/agent/config") in paths


def test_agent_config_via_admin_handlers_factory():
    """The handler is available on the AdminHandlers dataclass."""
    import unified_bridge as ub
    from arena.admin.handlers import make_admin_handlers
    from arena.handler_context import AdminHandlerContext

    ctx = AdminHandlerContext(
        require_auth=ub.require_auth,
        record_request=ub._record_request,
        cors_json_response=ub._cors_json_response,
        executor=ub._EXECUTOR,
        audit=ub.audit,
        default_token_file=Path("/tmp/token.txt"),
        root_agent=Path("/tmp"),
        subprocess_kwargs=ub._subprocess_kwargs,
    )
    handlers = make_admin_handlers(ctx)
    assert callable(handlers.agent_config)
