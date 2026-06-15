"""High-level /v1/browser/browse handler extraction tests."""
import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import unified_bridge as ub  # noqa: E402
from arena.browser.handlers import make_browser_browse_handlers  # noqa: E402
from arena.handler_context import BrowserBrowseHandlerContext  # noqa: E402


class _JsonRequest:
    def __init__(self, payload):
        self._payload = payload

    async def json(self):
        if isinstance(self._payload, BaseException):
            raise self._payload
        return self._payload


def _ctx(tmp_path: Path) -> BrowserBrowseHandlerContext:
    return BrowserBrowseHandlerContext(
        require_auth=lambda request: None,
        record_request=lambda *args, **kwargs: None,
        cors_json_response=ub._cors_json_response,
        app_dir=tmp_path,
        cdp_state={"connected": False, "port": 9222, "headless": True, "manager": None},
        get_cdp_module=lambda: None,
        start_cdp_watcher=lambda: None,
    )


def _json(response):
    return ub.json.loads(response.text)


def test_browser_browse_handlers_factory_outputs(tmp_path):
    handlers = make_browser_browse_handlers(_ctx(tmp_path))
    assert callable(handlers.browse)


def test_browser_browse_route_registered():
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
    assert ("POST", "/v1/browser/browse") in paths


def test_unified_browser_browse_handler_bound_to_browser_module():
    assert ub.handle_v1_browser_browse.__module__ == "arena.browser.browse_handlers"


def test_browser_browse_rejects_invalid_json(tmp_path):
    handler = make_browser_browse_handlers(_ctx(tmp_path)).browse
    response = asyncio.run(handler(_JsonRequest(ValueError("bad json"))))
    body = _json(response)
    assert response.status == 400
    assert body == {"ok": False, "error": "Invalid JSON body"}


def test_browser_browse_requires_url(tmp_path):
    handler = make_browser_browse_handlers(_ctx(tmp_path)).browse
    response = asyncio.run(handler(_JsonRequest({})))
    body = _json(response)
    assert response.status == 400
    assert body == {"ok": False, "error": "missing 'url'"}


def test_browser_browse_stealth_requires_browseract_skill(tmp_path):
    handler = make_browser_browse_handlers(_ctx(tmp_path)).browse
    response = asyncio.run(handler(_JsonRequest({"url": "https://example.com", "stealth": True})))
    body = _json(response)
    assert response.status == 503
    assert body == {"ok": False, "error": "BrowserAct skill not installed"}


def test_browser_browse_cdp_missing_module_returns_503(tmp_path):
    handler = make_browser_browse_handlers(_ctx(tmp_path)).browse
    response = asyncio.run(handler(_JsonRequest({"url": "https://example.com"})))
    body = _json(response)
    assert response.status == 503
    assert body == {"ok": False, "error": "CDP module not available"}
