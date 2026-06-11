"""Dashboard GUI handler factory smoke tests."""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import unified_bridge as ub  # noqa: E402
from arena.gui.handlers import DASHBOARD_V2_HTML, GUI_LOGIN_HTML, make_gui_handlers  # noqa: E402
from arena.handler_context import GuiHandlerContext  # noqa: E402


def test_gui_templates_reexported_for_compatibility():
    assert ub._GUI_LOGIN_HTML is GUI_LOGIN_HTML
    assert ub._DASHBOARD_V2_HTML is DASHBOARD_V2_HTML
    assert "Arena Bridge" in GUI_LOGIN_HTML
    assert "Dashboard v2" in DASHBOARD_V2_HTML


def test_gui_handlers_factory_outputs(tmp_path):
    ctx = GuiHandlerContext(
        cors_json_response=ub._cors_json_response,
        bridge_dir=tmp_path,
        version=ub.VERSION,
    )
    handlers = make_gui_handlers(ctx)
    assert callable(handlers.gui)
    assert callable(handlers.gui_v2)


def test_gui_routes_registered():
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
    paths = {(r.method, r.resource.get_info().get("path") or r.resource.get_info().get("formatter")) for r in app.router.routes()}
    assert ("GET", "/gui") in paths
    assert ("GET", "/gui/v2") in paths
