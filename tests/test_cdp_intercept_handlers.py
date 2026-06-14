"""CDP network interception handler extraction tests."""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import unified_bridge as ub  # noqa: E402
from arena.browser.cdp.intercept import make_cdp_intercept_handlers  # noqa: E402
from arena.handler_context import CdpInterceptHandlerContext  # noqa: E402


class _Request:
    def __init__(self, payload=None, method="POST"):
        self._payload = payload
        self.method = method

    async def json(self):
        if isinstance(self._payload, BaseException):
            raise self._payload
        if self._payload is None:
            raise ValueError("no json")
        return self._payload


class _Browser:
    pass


class _Tab:
    def __init__(self, with_browser=True):
        self._browser = _Browser() if with_browser else None


class _Rule:
    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.name = kwargs.get("name") or "rule"

    def to_dict(self):
        return dict(self.kwargs)


class _Interceptor:
    def __init__(self, browser=None):
        self.browser = browser
        self.active = False
        self.patterns = None
        self.rules = []
        self.stopped = False

    async def start(self, patterns=None):
        self.active = True
        self.patterns = patterns

    async def stop(self):
        self.active = False
        self.stopped = True

    def get_rules(self):
        return list(self.rules)

    def add_rule(self, rule):
        self.rules.append(rule)

    def remove_rule(self, name):
        before = len(self.rules)
        self.rules = [r for r in self.rules if r.name != name]
        return len(self.rules) != before


class _CdpModule:
    CDPNetworkInterceptor = _Interceptor
    InterceptRule = _Rule


def _ctx(state=None, cdp=None, tab=None) -> CdpInterceptHandlerContext:
    state = state if state is not None else {"connected": False, "interceptor": None}
    tab = tab if tab is not None else _Tab()

    async def active_tab(tab_id=None):
        return tab, None

    return CdpInterceptHandlerContext(
        require_auth=lambda request: None,
        record_request=lambda *args, **kwargs: None,
        cors_json_response=ub._cors_json_response,
        cdp_state=state,
        cdp_active_tab=active_tab,
        get_cdp_module=lambda: cdp,
    )


def _json(response):
    return ub.json.loads(response.text)


def test_cdp_intercept_handlers_factory_outputs():
    handlers = make_cdp_intercept_handlers(_ctx())
    assert callable(handlers.start)
    assert callable(handlers.stop)
    assert callable(handlers.rule)


def test_cdp_intercept_routes_registered():
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
        assert ("POST", f"{prefix}/intercept/start") in paths
        assert ("POST", f"{prefix}/intercept/stop") in paths
        assert ("POST", f"{prefix}/intercept/rule") in paths
        assert ("DELETE", f"{prefix}/intercept/rule") in paths
        assert ("GET", f"{prefix}/intercept/rules") in paths


def test_unified_cdp_intercept_handlers_bound_to_cdp_module():
    assert ub.handle_v1_cdp_intercept_start.__module__ == "arena.browser.cdp.intercept"
    assert ub.handle_v1_cdp_intercept_stop.__module__ == "arena.browser.cdp.intercept"
    assert ub.handle_v1_cdp_intercept_rule.__module__ == "arena.browser.cdp.intercept"


def test_cdp_intercept_start_disconnected_and_missing_module():
    disconnected = asyncio.run(make_cdp_intercept_handlers(_ctx()).start(_Request()))
    assert disconnected.status == 400
    assert _json(disconnected) == {"ok": False, "error": "CDP not connected"}

    missing = asyncio.run(make_cdp_intercept_handlers(_ctx({"connected": True, "interceptor": None})).start(_Request()))
    assert missing.status == 500
    assert _json(missing) == {"ok": False, "error": "cdp_browser module not found"}


def test_cdp_intercept_start_rule_list_delete_stop_flow():
    state = {"connected": True, "interceptor": None}
    handlers = make_cdp_intercept_handlers(_ctx(state, cdp=_CdpModule()))

    start = asyncio.run(handlers.start(_Request({"patterns": [{"urlPattern": "*"}]})))
    assert _json(start) == {"ok": True, "message": "Network interception started"}
    assert isinstance(state["interceptor"], _Interceptor)
    assert state["interceptor"].active is True

    add = asyncio.run(handlers.rule(_Request({"name": "r1", "action": "block", "url_pattern": "*ads*"}, method="POST")))
    add_body = _json(add)
    assert add_body["ok"] is True
    assert add_body["rule"]["name"] == "r1"
    assert add_body["rule"]["action"] == "block"

    rules = asyncio.run(handlers.rule(_Request(method="GET")))
    assert _json(rules)["count"] == 1

    delete = asyncio.run(handlers.rule(_Request({"name": "r1"}, method="DELETE")))
    assert _json(delete) == {"ok": True, "name": "r1"}

    stop = asyncio.run(handlers.stop(_Request()))
    assert _json(stop) == {"ok": True, "message": "Interception stopped"}
    assert state["interceptor"].stopped is True


def test_cdp_intercept_rule_validation():
    state = {"connected": True, "interceptor": _Interceptor()}
    handlers = make_cdp_intercept_handlers(_ctx(state, cdp=_CdpModule()))

    empty_rules = asyncio.run(handlers.rule(_Request(method="GET")))
    assert _json(empty_rules) == {"ok": True, "rules": [], "count": 0}

    missing_action = asyncio.run(handlers.rule(_Request({"name": "r"}, method="POST")))
    assert missing_action.status == 400
    assert _json(missing_action) == {"ok": False, "error": "Interception not active. Start first."}

    bad_delete = asyncio.run(handlers.rule(_Request({}, method="DELETE")))
    assert bad_delete.status == 400
    assert _json(bad_delete) == {"ok": False, "error": "missing 'name'"}
