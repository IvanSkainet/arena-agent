"""CDP cookie manager helper extraction tests."""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import unified_bridge as ub  # noqa: E402
from arena.browser.cdp.cookie_manager import ensure_cookie_manager  # noqa: E402
from arena.handler_context import CdpCookiesHandlerContext  # noqa: E402


class _Tab:
    target_id = "tab-1"
    connected = True
    _browser = None
    ws_url = "ws://tab"

    def __init__(self):
        self.sent = []

    async def send(self, method, params=None, timeout=None):
        self.sent.append((method, params, timeout))
        if method == "Network.getAllCookies":
            return {"result": {"cookies": [{"name": "sid", "domain": "example.com"}]}}
        if method == "Network.setCookie":
            return {"result": {"success": True}}
        return {"result": {}}


class _Manager:
    def __init__(self, tab):
        self._tab = tab

    def list_tabs(self):
        return [self._tab]


def _ctx(tab=None, cdp=object()):
    tab = tab or _Tab()

    async def active_tab(tab_id=None):
        return tab, None

    return CdpCookiesHandlerContext(
        require_auth=lambda request: None,
        record_request=lambda *args, **kwargs: None,
        cors_json_response=ub._cors_json_response,
        cdp_state={"connected": True, "manager": _Manager(tab), "cookie_mgr": None},
        cdp_active_tab=active_tab,
        get_cdp_module=lambda: cdp,
        log_info=lambda *args, **kwargs: None,
        log_warning=lambda *args, **kwargs: None,
        log_error=lambda *args, **kwargs: None,
    )


def test_ensure_cookie_manager_missing_cdp_module_returns_none():
    assert asyncio.run(ensure_cookie_manager(_ctx(cdp=None))) is None


def test_ensure_cookie_manager_falls_back_to_tab_level_manager():
    ctx = _ctx()
    manager = asyncio.run(ensure_cookie_manager(ctx))
    assert manager is ctx.cdp_state["cookie_mgr"]
    assert manager.active is True
    cookies = asyncio.run(manager.get_all_cookies())
    assert cookies == [{"name": "sid", "domain": "example.com"}]
    assert asyncio.run(manager.set_cookie(name="sid", value="1")) is True
