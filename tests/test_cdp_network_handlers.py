"""CDP network monitoring handler extraction tests."""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import unified_bridge as ub  # noqa: E402
from arena.browser.cdp.network import make_cdp_network_handlers  # noqa: E402
from arena.handler_context import CdpNetworkHandlerContext  # noqa: E402


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


class _Browser:
    pass


class _Tab:
    def __init__(self):
        self._browser = _Browser()


class _Req:
    def __init__(self, url="https://example.com", resource_type="Document"):
        self.url = url
        self.resource_type = resource_type

    def to_dict(self):
        return {"url": self.url, "resource_type": self.resource_type}


class _Monitor:
    def __init__(self, browser=None, max_entries=1000):
        self.browser = browser
        self.max_entries = max_entries
        self.active = False
        self.total_requests = 1
        self.active_count = 1
        self.stopped = False

    async def start(self):
        self.active = True

    async def stop(self):
        self.active = False
        self.stopped = True

    def get_requests(self, url_filter=None, resource_type=None):
        reqs = [_Req()]
        if url_filter:
            reqs = [r for r in reqs if url_filter in r.url]
        if resource_type:
            reqs = [r for r in reqs if resource_type == r.resource_type]
        return reqs

    def get_active_requests(self):
        return [_Req("https://active.example.com", "XHR")]

    def export_har(self):
        return {"log": {"version": "1.2", "entries": [{"request": {"url": "https://example.com"}}]}}


class _CdpModule:
    CDPNetworkMonitor = _Monitor


def _ctx(state=None, cdp=None, tab=None) -> CdpNetworkHandlerContext:
    state = state if state is not None else {"connected": False, "monitor": None}
    tab = tab or _Tab()

    async def active_tab(tab_id=None):
        return tab, None

    return CdpNetworkHandlerContext(
        require_auth=lambda request: None,
        record_request=lambda *args, **kwargs: None,
        cors_json_response=ub._cors_json_response,
        cdp_state=state,
        cdp_active_tab=active_tab,
        get_cdp_module=lambda: cdp,
    )


def _json(response):
    return ub.json.loads(response.text)


def test_cdp_network_handlers_factory_outputs():
    handlers = make_cdp_network_handlers(_ctx())
    assert callable(handlers.start)
    assert callable(handlers.stop)
    assert callable(handlers.requests)
    assert callable(handlers.har)


def test_cdp_network_routes_registered():
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
        assert ("POST", f"{prefix}/network/start") in paths
        assert ("POST", f"{prefix}/network/stop") in paths
        assert ("GET", f"{prefix}/network/requests") in paths
        assert ("GET", f"{prefix}/network/har") in paths


def test_unified_cdp_network_handlers_bound_to_cdp_module():
    assert ub.handle_v1_cdp_network_start.__module__ == "arena.browser.cdp.network"
    assert ub.handle_v1_cdp_network_stop.__module__ == "arena.browser.cdp.network"
    assert ub.handle_v1_cdp_network_requests.__module__ == "arena.browser.cdp.network"
    assert ub.handle_v1_cdp_network_har.__module__ == "arena.browser.cdp.network"


def test_cdp_network_start_disconnected_and_missing_module():
    disconnected = asyncio.run(make_cdp_network_handlers(_ctx()).start(_Request()))
    assert disconnected.status == 400
    assert _json(disconnected) == {"ok": False, "error": "CDP not connected"}

    missing = asyncio.run(make_cdp_network_handlers(_ctx({"connected": True, "monitor": None})).start(_Request()))
    assert missing.status == 500
    assert _json(missing) == {"ok": False, "error": "cdp_browser module not found"}


def test_cdp_network_start_stop_requests_har_flow():
    state = {"connected": True, "monitor": None}
    handlers = make_cdp_network_handlers(_ctx(state, cdp=_CdpModule()))

    start = asyncio.run(handlers.start(_Request({"max_entries": 5})))
    assert _json(start) == {"ok": True, "message": "Network monitoring started", "max_entries": 5}
    assert isinstance(state["monitor"], _Monitor)
    assert state["monitor"].active is True
    assert state["monitor"].max_entries == 5

    requests = asyncio.run(handlers.requests(_Request(query_string="include_active=true")))
    body = _json(requests)
    assert body["ok"] is True
    assert body["total_finished"] == 1
    assert body["active_count"] == 1
    assert body["requests"] == [{"url": "https://example.com", "resource_type": "Document"}]
    assert body["active"] == [{"url": "https://active.example.com", "resource_type": "XHR"}]

    har = asyncio.run(handlers.har(_Request()))
    assert _json(har)["log"]["entries"][0]["request"]["url"] == "https://example.com"

    stop = asyncio.run(handlers.stop(_Request()))
    assert _json(stop) == {"ok": True, "message": "Network monitoring stopped"}
    assert state["monitor"].stopped is True


def test_cdp_network_requests_and_har_when_no_monitor():
    handlers = make_cdp_network_handlers(_ctx())
    assert _json(asyncio.run(handlers.requests(_Request()))) == {"ok": True, "requests": [], "count": 0, "active_count": 0}
    assert _json(asyncio.run(handlers.har(_Request()))) == {"log": {"version": "1.2", "creator": {"name": "arena-cdp", "version": "1.0"}, "entries": []}}
