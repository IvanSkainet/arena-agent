"""CDP session connect/disconnect handler extraction tests."""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import unified_bridge as ub  # noqa: E402
from arena.browser.cdp.session import make_cdp_session_handlers  # noqa: E402
from arena.handler_context import CdpSessionHandlerContext  # noqa: E402


class _Request:
    def __init__(self, payload=None):
        self._payload = payload

    async def json(self):
        if isinstance(self._payload, BaseException):
            raise self._payload
        if self._payload is None:
            raise ValueError("no json")
        return self._payload


class _Tab:
    connected = True
    target_id = "tab-1"
    ws_url = "ws://old"

    async def connect(self):
        self.connected = True

    def to_dict(self):
        return {"id": "tab-1", "url": "about:blank"}


class _Manager:
    def __init__(self, port=9222, headless=True, auto_launch=True):
        self.port = port
        self.headless = headless
        self.auto_launch = auto_launch
        self.tab_count = 1
        self.active_tab_id = "tab-1"
        self.active_tab = _Tab()
        self.ws_diagnostics = {"ok": True}
        self._browser_proc = None
        self.closed = False

    async def connect(self):
        return None

    async def close(self):
        self.closed = True

    def list_tabs(self):
        return [self.active_tab]


class _CdpModule:
    CDPTabManager = _Manager


class _Component:
    def __init__(self):
        self.active = True
        self.stopped = False

    async def stop(self):
        self.stopped = True
        self.active = False


def _base_state():
    return {
        "manager": None,
        "monitor": None,
        "interceptor": None,
        "cookie_mgr": None,
        "connected": False,
        "port": 9222,
        "headless": True,
        "last_connect_time": None,
        "last_disconnect_reason": None,
    }


def _ctx(state=None, cdp=None, events=None, watcher=None) -> CdpSessionHandlerContext:
    state = state or _base_state()
    events = events if events is not None else []
    watcher = watcher if watcher is not None else {"started": 0, "stopped": 0}

    async def emit_event(event_type, data=None):
        events.append((event_type, data))

    return CdpSessionHandlerContext(
        require_auth=lambda request: None,
        record_request=lambda *args, **kwargs: None,
        cors_json_response=ub._cors_json_response,
        cdp_state=state,
        cdp_connect_lock=asyncio.Lock(),
        get_cdp_module=lambda: cdp,
        start_cdp_watcher=lambda: watcher.__setitem__("started", watcher["started"] + 1),
        stop_cdp_watcher=lambda: watcher.__setitem__("stopped", watcher["stopped"] + 1),
        emit_event=emit_event,
        log_info=lambda *args, **kwargs: None,
        log_warning=lambda *args, **kwargs: None,
    )


def _json(response):
    return ub.json.loads(response.text)


def test_cdp_session_handlers_factory_outputs():
    handlers = make_cdp_session_handlers(_ctx())
    assert callable(handlers.connect)
    assert callable(handlers.disconnect)


def test_cdp_session_routes_registered():
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
    assert ("POST", "/v1/browser/cdp/connect") in paths
    assert ("POST", "/v1/browser/cdp/disconnect") in paths
    assert ("POST", "/v1/cdp/connect") in paths
    assert ("POST", "/v1/cdp/disconnect") in paths


def test_unified_cdp_session_handlers_bound_to_cdp_module():
    assert ub.handle_v1_cdp_connect.__module__ == "arena.browser.cdp.session_connect"
    assert ub.handle_v1_cdp_disconnect.__module__ == "arena.browser.cdp.session_disconnect"


def test_cdp_connect_missing_module():
    response = asyncio.run(make_cdp_session_handlers(_ctx()).connect(_Request()))
    body = _json(response)
    assert response.status == 500
    assert body == {"ok": False, "error": "cdp_browser module not found. Install to scripts/ directory."}


def test_cdp_connect_success_updates_state_and_starts_watcher():
    state = _base_state()
    watcher = {"started": 0, "stopped": 0}
    handler = make_cdp_session_handlers(_ctx(state=state, cdp=_CdpModule(), watcher=watcher)).connect
    response = asyncio.run(handler(_Request({"port": 9333, "headless": False})))
    body = _json(response)
    assert body["ok"] is True
    assert body["message"] == "CDP connected"
    assert body["port"] == 9333
    assert body["headless"] is False
    assert state["connected"] is True
    assert state["port"] == 9333
    assert state["manager"] is not None
    assert state["last_connect_time"]
    assert watcher["started"] == 1


def test_cdp_disconnect_not_connected():
    response = asyncio.run(make_cdp_session_handlers(_ctx()).disconnect(_Request()))
    body = _json(response)
    assert body == {"ok": True, "message": "Not connected"}


def test_cdp_disconnect_stops_components_closes_manager_and_resets_state():
    state = _base_state()
    state["connected"] = True
    state["manager"] = _Manager()
    state["monitor"] = _Component()
    state["interceptor"] = _Component()
    state["cookie_mgr"] = _Component()
    watcher = {"started": 0, "stopped": 0}
    response = asyncio.run(make_cdp_session_handlers(_ctx(state=state, watcher=watcher)).disconnect(_Request()))
    body = _json(response)
    assert body == {"ok": True, "message": "CDP disconnected"}
    assert state["connected"] is False
    assert state["manager"] is None
    assert state["monitor"] is None
    assert state["interceptor"] is None
    assert state["cookie_mgr"] is None
    assert state["last_disconnect_reason"] == "User disconnected"
    assert watcher["stopped"] == 1
