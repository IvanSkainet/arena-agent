"""CDP page action handler extraction tests."""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import unified_bridge as ub  # noqa: E402
from arena.browser.cdp.page import make_cdp_page_handlers  # noqa: E402
from arena.handler_context import CdpPageHandlerContext  # noqa: E402


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


class _Tab:
    target_id = "tab-1"

    def __init__(self):
        self.navigated = None

    async def navigate(self, url, wait=True, timeout=28):
        self.navigated = (url, wait, timeout)
        return {"frameId": "frame-1"}

    async def screenshot(self, path=None, timeout=18):
        return b"png-bytes"

    async def dump_dom(self, timeout=18):
        return "<html>ok</html>"

    async def send(self, method, params=None):
        if method == "Runtime.evaluate":
            return {"result": {"result": {"value": 42}}}
        return {"result": {}}

    async def click(self, selector, timeout=14):
        return True

    async def click_at(self, x, y, timeout=14):
        return True

    async def type_text(self, selector, text, timeout=14):
        return True


class _Manager:
    def __init__(self):
        self.synced = False

    async def sync_tabs(self):
        self.synced = True


def _ctx(tab=None, err=None, state=None) -> CdpPageHandlerContext:
    tab = tab or _Tab()
    state = state or {"manager": _Manager(), "last_navigation_time": None}

    async def active_tab(tab_id=None):
        return tab, err

    return CdpPageHandlerContext(
        require_auth=lambda request: None,
        record_request=lambda *args, **kwargs: None,
        cors_json_response=ub._cors_json_response,
        cdp_state=state,
        cdp_active_tab=active_tab,
        default_max_output=100000,
        log_debug=lambda *args, **kwargs: None,
        log_warning=lambda *args, **kwargs: None,
        log_error=lambda *args, **kwargs: None,
    )


def _json(response):
    return ub.json.loads(response.text)


def test_cdp_page_handlers_factory_outputs():
    handlers = make_cdp_page_handlers(_ctx())
    assert callable(handlers.navigate)
    assert callable(handlers.screenshot)
    assert callable(handlers.dom)
    assert callable(handlers.eval)
    assert callable(handlers.click)
    assert callable(handlers.type)


def test_cdp_page_routes_registered():
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
        assert ("POST", f"{prefix}/navigate") in paths
        assert ("GET", f"{prefix}/screenshot") in paths
        assert ("GET", f"{prefix}/dom") in paths
        assert ("POST", f"{prefix}/eval") in paths
        assert ("POST", f"{prefix}/click") in paths
        assert ("POST", f"{prefix}/type") in paths


def test_unified_cdp_page_handlers_bound_to_cdp_module():
    assert ub.handle_v1_cdp_navigate.__module__ == "arena.browser.cdp.page"
    assert ub.handle_v1_cdp_screenshot.__module__ == "arena.browser.cdp.page"
    assert ub.handle_v1_cdp_dom.__module__ == "arena.browser.cdp.page"
    assert ub.handle_v1_cdp_eval.__module__ == "arena.browser.cdp.page"
    assert ub.handle_v1_cdp_click.__module__ == "arena.browser.cdp.page"
    assert ub.handle_v1_cdp_type.__module__ == "arena.browser.cdp.page"


def test_cdp_navigate_requires_valid_json_and_url():
    handler = make_cdp_page_handlers(_ctx()).navigate
    bad_json = asyncio.run(handler(_Request(ValueError("bad"))))
    assert bad_json.status == 400
    assert _json(bad_json) == {"ok": False, "error": "Invalid JSON body"}

    missing = asyncio.run(handler(_Request({})))
    assert missing.status == 400
    assert _json(missing) == {"ok": False, "error": "missing 'url' parameter"}


def test_cdp_navigate_success_updates_navigation_time_and_syncs_tabs():
    tab = _Tab()
    manager = _Manager()
    state = {"manager": manager, "last_navigation_time": None}
    handler = make_cdp_page_handlers(_ctx(tab=tab, state=state)).navigate
    response = asyncio.run(handler(_Request({"url": "https://example.com", "wait": False})))
    body = _json(response)
    assert body["ok"] is True
    assert body["url"] == "https://example.com"
    assert body["tab_id"] == "tab-1"
    assert tab.navigated == ("https://example.com", False, 28)
    assert state["last_navigation_time"] is not None
    assert manager.synced is True


def test_cdp_screenshot_base64_success():
    handler = make_cdp_page_handlers(_ctx()).screenshot
    response = asyncio.run(handler(_Request(query_string="format=base64")))
    body = _json(response)
    assert body["ok"] is True
    assert body["format"] == "base64"
    assert body["size_bytes"] == len(b"png-bytes")
    assert body["tab_id"] == "tab-1"


def test_cdp_eval_click_type_success():
    handlers = make_cdp_page_handlers(_ctx())
    eval_response = asyncio.run(handlers.eval(_Request({"expression": "21*2"})))
    assert _json(eval_response)["result"] == "42"

    click_response = asyncio.run(handlers.click(_Request({"selector": "button"})))
    assert _json(click_response)["mode"] == "selector"

    type_response = asyncio.run(handlers.type(_Request({"selector": "input", "text": "hi"})))
    assert _json(type_response)["typed"] is True
