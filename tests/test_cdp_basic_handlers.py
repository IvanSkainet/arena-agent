"""Lightweight CDP status/diagnostic handler extraction tests."""
import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import unified_bridge as ub  # noqa: E402
from arena.browser.cdp.handlers import make_cdp_basic_handlers  # noqa: E402
from arena.handler_context import CdpBasicHandlerContext  # noqa: E402


class _Tab:
    def to_dict(self):
        return {"id": "tab-1", "url": "about:blank"}


class _Manager:
    tab_count = 1
    active_tab_id = "tab-1"

    def list_tabs(self):
        return [_Tab()]


def _ctx(state=None, cdp=None, watcher_active=False) -> CdpBasicHandlerContext:
    return CdpBasicHandlerContext(
        require_auth=lambda request: None,
        record_request=lambda *args, **kwargs: None,
        cors_json_response=ub._cors_json_response,
        cdp_state=state or {
            "manager": None,
            "monitor": None,
            "interceptor": None,
            "cookie_mgr": None,
            "connected": False,
            "port": 9222,
            "headless": True,
            "reconnect_count": 0,
            "last_connect_time": None,
            "last_disconnect_reason": None,
        },
        get_cdp_module=lambda: cdp,
        watcher_active=lambda: watcher_active,
    )


def _json(response):
    return ub.json.loads(response.text)


def test_cdp_basic_handlers_factory_outputs():
    handlers = make_cdp_basic_handlers(_ctx())
    assert callable(handlers.status)
    assert callable(handlers.diag)


def test_cdp_basic_routes_registered():
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
    assert ("GET", "/v1/browser/cdp/status") in paths
    assert ("GET", "/v1/browser/cdp/diag") in paths
    assert ("GET", "/v1/cdp/status") in paths
    assert ("GET", "/v1/cdp/diag") in paths


def test_unified_cdp_basic_handlers_bound_to_cdp_module():
    assert ub.handle_v1_cdp_status.__module__ == "arena.browser.cdp.handlers"
    assert ub.handle_v1_cdp_diag.__module__ == "arena.browser.cdp.handlers"


def test_cdp_status_reports_manager_and_runtime_state():
    state = {
        "manager": _Manager(),
        "monitor": SimpleNamespace(active=True),
        "interceptor": SimpleNamespace(active=False),
        "cookie_mgr": SimpleNamespace(active=True),
        "connected": True,
        "port": 9333,
        "headless": False,
        "reconnect_count": 2,
        "last_connect_time": "now",
        "last_disconnect_reason": "old",
    }
    response = asyncio.run(make_cdp_basic_handlers(_ctx(state=state, cdp=object(), watcher_active=True)).status(object()))
    body = _json(response)
    assert body["ok"] is True
    assert body["connected"] is True
    assert body["module_available"] is True
    assert body["tab_count"] == 1
    assert body["active_tab_id"] == "tab-1"
    assert body["network_monitoring"] is True
    assert body["interception_active"] is False
    assert body["cookie_manager_active"] is True
    assert body["watcher_active"] is True
    assert body["tabs"] == [{"id": "tab-1", "url": "about:blank"}]
