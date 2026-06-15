"""CDP cookie/profile handler extraction tests."""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import unified_bridge as ub  # noqa: E402
from arena.browser.cdp.cookies import make_cdp_cookies_handlers  # noqa: E402
from arena.handler_context import CdpCookiesHandlerContext  # noqa: E402


class _Request:
    def __init__(self, payload=None, query_string="", method="GET"):
        self._payload = payload
        self.query_string = query_string
        self.method = method

    async def json(self):
        if isinstance(self._payload, BaseException):
            raise self._payload
        if self._payload is None:
            raise ValueError("no json")
        return self._payload


class _CookieMgr:
    active = True

    def __init__(self):
        self.cookies = [
            {"name": "sid", "value": "1", "domain": ".example.com"},
            {"name": "other", "value": "2", "domain": ".other.com"},
        ]
        self.set_calls = []
        self.deleted = []
        self.cleared = False
        self.profiles = {"p1": {"name": "p1", "cookie_count": 2}}

    async def get_all_cookies(self):
        return list(self.cookies)

    async def get_cookies_for_url(self, url):
        return [self.cookies[0]]

    async def set_cookie(self, **kwargs):
        self.set_calls.append(kwargs)
        return True

    async def delete_cookie(self, name, domain=""):
        self.deleted.append((name, domain))

    async def clear_cookies(self):
        self.cleared = True

    def list_profiles(self):
        return list(self.profiles)

    def get_profile_info(self, name):
        return self.profiles[name]

    async def save_profile(self, name, domain_filter=None):
        return 2

    async def restore_profile(self, name, clear_first=True):
        return 2

    def delete_profile(self, name):
        return True


def _ctx(state=None) -> CdpCookiesHandlerContext:
    state = state if state is not None else {"connected": False, "cookie_mgr": None}

    async def active_tab(tab_id=None):
        return None, None

    return CdpCookiesHandlerContext(
        require_auth=lambda request: None,
        record_request=lambda *args, **kwargs: None,
        cors_json_response=ub._cors_json_response,
        cdp_state=state,
        cdp_active_tab=active_tab,
        get_cdp_module=lambda: None,
        log_info=lambda *args, **kwargs: None,
        log_warning=lambda *args, **kwargs: None,
        log_error=lambda *args, **kwargs: None,
    )


def _json(response):
    return ub.json.loads(response.text)


def test_cdp_cookies_handlers_factory_outputs():
    handlers = make_cdp_cookies_handlers(_ctx())
    assert callable(handlers.get)
    assert callable(handlers.set)
    assert callable(handlers.delete)
    assert callable(handlers.clear)
    assert callable(handlers.profiles)


def test_cdp_cookies_routes_registered():
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
        assert ("GET", f"{prefix}/cookies") in paths
        assert ("POST", f"{prefix}/cookies") in paths
        assert ("DELETE", f"{prefix}/cookies") in paths
        assert ("POST", f"{prefix}/cookies/clear") in paths
        assert ("GET", f"{prefix}/cookies/profiles") in paths
        assert ("POST", f"{prefix}/cookies/profiles") in paths


def test_unified_cdp_cookies_handlers_bound_to_cdp_modules():
    assert ub.handle_v1_cdp_cookies_get.__module__ == "arena.browser.cdp.cookie_crud"
    assert ub.handle_v1_cdp_cookies_set.__module__ == "arena.browser.cdp.cookie_crud"
    assert ub.handle_v1_cdp_cookies_delete.__module__ == "arena.browser.cdp.cookie_crud"
    assert ub.handle_v1_cdp_cookies_clear.__module__ == "arena.browser.cdp.cookie_crud"
    assert ub.handle_v1_cdp_cookies_profiles.__module__ == "arena.browser.cdp.cookie_profiles"


def test_cdp_cookies_disconnected_returns_400():
    response = asyncio.run(make_cdp_cookies_handlers(_ctx()).get(_Request()))
    assert response.status == 400
    assert _json(response) == {"ok": False, "error": "CDP not connected"}


def test_cdp_cookies_get_filters_and_set_delete_clear():
    mgr = _CookieMgr()
    state = {"connected": True, "cookie_mgr": mgr}
    handlers = make_cdp_cookies_handlers(_ctx(state))

    all_response = asyncio.run(handlers.get(_Request()))
    assert _json(all_response)["count"] == 2

    domain_response = asyncio.run(handlers.get(_Request(query_string="domain=example.com")))
    assert _json(domain_response)["cookies"] == [mgr.cookies[0]]

    set_response = asyncio.run(handlers.set(_Request({"name": "a", "value": "b", "domain": ".example.com"})))
    assert _json(set_response) == {"ok": True, "name": "a", "domain": ".example.com"}
    assert mgr.set_calls[-1]["name"] == "a"

    delete_response = asyncio.run(handlers.delete(_Request({"name": "a", "domain": ".example.com"})))
    assert _json(delete_response) == {"ok": True, "deleted": "a"}
    assert mgr.deleted == [("a", ".example.com")]

    clear_response = asyncio.run(handlers.clear(_Request()))
    assert _json(clear_response) == {"ok": True, "message": "All cookies cleared"}
    assert mgr.cleared is True


def test_cdp_cookies_validation_and_profiles():
    mgr = _CookieMgr()
    state = {"connected": True, "cookie_mgr": mgr}
    handlers = make_cdp_cookies_handlers(_ctx(state))

    missing_set = asyncio.run(handlers.set(_Request({"name": "a"})))
    assert missing_set.status == 400
    assert _json(missing_set) == {"ok": False, "error": "missing 'name' or 'value'"}

    profiles_get = asyncio.run(handlers.profiles(_Request(method="GET")))
    assert _json(profiles_get) == {"ok": True, "profiles": [{"name": "p1", "cookie_count": 2}], "count": 1}

    profiles_save = asyncio.run(handlers.profiles(_Request({"action": "save", "name": "p2"}, method="POST")))
    assert _json(profiles_save) == {"ok": True, "action": "save", "profile": "p2", "cookie_count": 2}

    profiles_bad = asyncio.run(handlers.profiles(_Request({"action": "bad", "name": "p2"}, method="POST")))
    assert profiles_bad.status == 400
    assert "Unknown action" in _json(profiles_bad)["error"]
