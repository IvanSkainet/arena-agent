"""CDP tabs handler extraction tests."""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import unified_bridge as ub  # noqa: E402
from arena.browser.cdp.tabs import make_cdp_tabs_handlers  # noqa: E402
from arena.handler_context import CdpTabsHandlerContext  # noqa: E402


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
    def __init__(self, target_id="tab-1", connected=True, ws_url="ws://tab"):
        self.target_id = target_id
        self.connected = connected
        self.ws_url = ws_url
        self.connect_called = False

    async def connect(self):
        self.connect_called = True
        self.connected = True

    def to_dict(self):
        return {"target_id": self.target_id, "connected": self.connected, "ws_url": self.ws_url}


class _Manager:
    def __init__(self):
        self.tabs = [_Tab("tab-1")]
        self.active_tab_id = "tab-1"

    @property
    def tab_count(self):
        return len(self.tabs)

    def list_tabs(self):
        return self.tabs

    async def new_tab(self, url, activate=True):
        tab = _Tab(f"tab-{len(self.tabs) + 1}")
        tab.url = url
        self.tabs.append(tab)
        if activate:
            self.active_tab_id = tab.target_id
        return tab

    async def close_tab(self, tab_id):
        before = len(self.tabs)
        self.tabs = [t for t in self.tabs if t.target_id != tab_id]
        if self.active_tab_id == tab_id:
            self.active_tab_id = self.tabs[0].target_id if self.tabs else None
        return len(self.tabs) != before

    def activate(self, tab_id):
        if any(t.target_id == tab_id for t in self.tabs):
            self.active_tab_id = tab_id
            return True
        return False


def _ctx(state=None) -> CdpTabsHandlerContext:
    return CdpTabsHandlerContext(
        require_auth=lambda request: None,
        record_request=lambda *args, **kwargs: None,
        cors_json_response=ub._cors_json_response,
        cdp_state=state if state is not None else {"connected": False, "manager": None},
        log_debug=lambda *args, **kwargs: None,
    )


def _json(response):
    return ub.json.loads(response.text)


def test_cdp_tabs_handlers_factory_outputs():
    handlers = make_cdp_tabs_handlers(_ctx())
    assert callable(handlers.tabs)
    assert callable(handlers.new)
    assert callable(handlers.close)
    assert callable(handlers.activate)


def test_cdp_tabs_routes_registered():
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
    for prefix in ("/v1/browser/cdp", "/v1/cdp"):
        assert ("GET", f"{prefix}/tabs") in paths
        assert ("POST", f"{prefix}/tabs/new") in paths
        assert ("POST", f"{prefix}/tabs/close") in paths
        assert ("POST", f"{prefix}/tabs/activate") in paths


def test_unified_cdp_tabs_handlers_bound_to_cdp_module():
    assert ub.handle_v1_cdp_tabs.__module__ == "arena.browser.cdp.tabs"
    assert ub.handle_v1_cdp_tabs_new.__module__ == "arena.browser.cdp.tabs"
    assert ub.handle_v1_cdp_tabs_close.__module__ == "arena.browser.cdp.tabs"
    assert ub.handle_v1_cdp_tabs_activate.__module__ == "arena.browser.cdp.tabs"


def test_cdp_tabs_disconnected_returns_empty_or_error():
    handlers = make_cdp_tabs_handlers(_ctx())
    tabs = asyncio.run(handlers.tabs(_Request()))
    assert _json(tabs) == {"ok": True, "tabs": [], "tab_count": 0}

    new = asyncio.run(handlers.new(_Request({})))
    assert new.status == 400
    assert _json(new) == {"ok": False, "error": "CDP not connected"}


def test_cdp_tabs_list_auto_connects_disconnected_tabs():
    manager = _Manager()
    manager.tabs.append(_Tab("tab-2", connected=False, ws_url="ws://tab2"))
    state = {"connected": True, "manager": manager}
    response = asyncio.run(make_cdp_tabs_handlers(_ctx(state)).tabs(_Request()))
    body = _json(response)
    assert body["ok"] is True
    assert body["tab_count"] == 2
    assert manager.tabs[1].connect_called is True
    assert manager.tabs[1].connected is True


def test_cdp_tabs_new_close_activate_flow():
    manager = _Manager()
    state = {"connected": True, "manager": manager}
    handlers = make_cdp_tabs_handlers(_ctx(state))

    new = asyncio.run(handlers.new(_Request({"url": "https://example.com", "activate": True})))
    new_body = _json(new)
    assert new_body["ok"] is True
    new_tab_id = new_body["tab_id"]
    assert manager.active_tab_id == new_tab_id

    activate = asyncio.run(handlers.activate(_Request({"tab_id": "tab-1"})))
    assert _json(activate) == {"ok": True, "tab_id": "tab-1", "active_tab_id": "tab-1"}

    close = asyncio.run(handlers.close(_Request({"tab_id": new_tab_id})))
    close_body = _json(close)
    assert close_body["ok"] is True
    assert close_body["tab_id"] == new_tab_id
    assert close_body["remaining_tabs"] == 1


def test_cdp_tabs_close_activate_validate_json_and_tab_id():
    manager = _Manager()
    state = {"connected": True, "manager": manager}
    handlers = make_cdp_tabs_handlers(_ctx(state))

    bad = asyncio.run(handlers.close(_Request(ValueError("bad"))))
    assert bad.status == 400
    assert _json(bad) == {"ok": False, "error": "Invalid JSON body"}

    missing = asyncio.run(handlers.activate(_Request({})))
    assert missing.status == 400
    assert _json(missing) == {"ok": False, "error": "missing 'tab_id'"}
