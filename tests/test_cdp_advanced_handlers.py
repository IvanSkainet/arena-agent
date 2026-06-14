"""Advanced CDP handler extraction tests."""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import unified_bridge as ub  # noqa: E402
from arena.browser.cdp.advanced import make_cdp_advanced_handlers  # noqa: E402
from arena.handler_context import CdpAdvancedHandlerContext  # noqa: E402


class _Request:
    def __init__(self, payload=None, query_string=""):
        self._payload = payload
        self.query_string = query_string

    async def json(self):
        if isinstance(self._payload, BaseException):
            raise self._payload
        if self._payload is None:
            raise ValueError("no json")
        return self._payload


class _CookieMgr:
    async def check_session(self, domain, auth_cookie_names=None):
        return {"domain": domain, "healthy": True, "auth_cookie_names": auth_cookie_names}


class _Browser:
    def __init__(self):
        self.url = "about:blank"

    async def navigate(self, url, wait=True):
        self.url = url

    async def eval_js(self, expr):
        if expr == "document.title":
            return "Title"
        if expr == "window.location.href":
            return self.url
        if "document.body" in expr:
            return "Hello world"
        if "meta" in expr:
            return '{"description":"Desc"}'
        return True

    async def dump_dom(self):
        return "<html><body>Hello world</body></html>"

    async def send(self, method, params=None):
        if method == "Page.captureScreenshot":
            return {"result": {"data": "BASE64PNG"}}
        return {"result": {}}


class _Tab:
    target_id = "tab-1"
    url = "about:blank"
    title = "Tab"
    connected = True

    def __init__(self):
        self._browser = _Browser()

    def to_dict(self):
        return {"target_id": self.target_id, "url": self.url, "title": self.title, "connected": self.connected}

    async def eval_js(self, expr):
        if expr == "1+1":
            return 2
        return None


class _Proc:
    pid = 123
    returncode = None

    def poll(self):
        return None


class _Manager:
    def __init__(self):
        self.active_tab = _Tab()
        self.active_tab_id = "tab-1"
        self._browser_proc = _Proc()

    def list_tabs(self):
        return [self.active_tab]


def _ctx(state=None, cookie_mgr=None) -> CdpAdvancedHandlerContext:
    async def ensure_cookie_manager():
        return cookie_mgr

    return CdpAdvancedHandlerContext(
        require_auth=lambda request: None,
        record_request=lambda *args, **kwargs: None,
        cors_json_response=ub._cors_json_response,
        cdp_state=state if state is not None else {"connected": False, "port": 9222, "headless": True, "manager": None},
        ensure_cookie_manager=ensure_cookie_manager,
        watcher_active=lambda: False,
        bridge_start_time=ub.time.time() - 10,
    )


def _json(response):
    return ub.json.loads(response.text)


def test_cdp_advanced_handlers_factory_outputs():
    handlers = make_cdp_advanced_handlers(_ctx())
    assert callable(handlers.session_check)
    assert callable(handlers.stealth_extract)
    assert callable(handlers.stealth_shot)
    assert callable(handlers.health)


def test_cdp_advanced_routes_registered():
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
        assert ("GET", f"{prefix}/session/check") in paths
        assert ("POST", f"{prefix}/stealth/extract") in paths
        assert ("POST", f"{prefix}/stealth/shot") in paths
        assert ("GET", f"{prefix}/health") in paths


def test_unified_cdp_advanced_handlers_bound_to_cdp_module():
    assert ub.handle_v1_cdp_session_check.__module__ == "arena.browser.cdp.advanced"
    assert ub.handle_v1_cdp_stealth_extract.__module__ == "arena.browser.cdp.advanced"
    assert ub.handle_v1_cdp_stealth_shot.__module__ == "arena.browser.cdp.advanced"
    assert ub.handle_v1_cdp_health.__module__ == "arena.browser.cdp.advanced"


def test_session_check_disconnected_and_success():
    handlers = make_cdp_advanced_handlers(_ctx())
    disconnected = asyncio.run(handlers.session_check(_Request(query_string="domain=example.com")))
    body = _json(disconnected)
    assert body["ok"] is False
    assert body["connected"] is False

    state = {"connected": True, "port": 9222, "headless": True, "manager": None}
    ok = asyncio.run(make_cdp_advanced_handlers(_ctx(state, _CookieMgr())).session_check(_Request(query_string="domain=example.com&auth_cookie_names=sid,auth")))
    assert _json(ok) == {"ok": True, "domain": "example.com", "healthy": True, "auth_cookie_names": ["sid", "auth"]}


def test_stealth_extract_and_shot_success():
    state = {"connected": True, "port": 9222, "headless": True, "manager": _Manager()}
    handlers = make_cdp_advanced_handlers(_ctx(state))

    extract = asyncio.run(handlers.stealth_extract(_Request({"url": "https://example.com"})))
    body = _json(extract)
    assert body["ok"] is True
    assert body["title"] == "Title"
    assert body["text"] == "Hello world"
    assert body["metadata"] == {"description": "Desc"}

    shot = asyncio.run(handlers.stealth_shot(_Request({"url": "https://example.com", "width": 800, "height": 600})))
    shot_body = _json(shot)
    assert shot_body["ok"] is True
    assert shot_body["data"] == "BASE64PNG"
    assert shot_body["width"] == 800
    assert shot_body["height"] == 600


def test_health_disconnected_and_connected():
    disconnected = asyncio.run(make_cdp_advanced_handlers(_ctx()).health(_Request()))
    body = _json(disconnected)
    assert body["ok"] is True
    assert body["connected"] is False
    assert body["tabs"] == {"count": 0}

    state = {
        "connected": True,
        "port": 9222,
        "headless": True,
        "manager": _Manager(),
        "reconnect_count": 1,
        "last_connect_time": "2026-06-14T00:00:00+00:00",
        "last_disconnect_reason": None,
    }
    connected = asyncio.run(make_cdp_advanced_handlers(_ctx(state)).health(_Request()))
    cbody = _json(connected)
    assert cbody["ok"] is True
    assert cbody["connected"] is True
    assert cbody["tabs"]["count"] == 1
    assert cbody["active_tab"]["health_probe"] == "ok"
