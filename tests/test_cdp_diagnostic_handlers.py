"""CDP diagnostic handler extraction tests."""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import unified_bridge as ub  # noqa: E402
from arena.browser.cdp.diagnostics import make_cdp_diagnostic_handlers  # noqa: E402
from arena.handler_context import CdpDiagnosticHandlerContext  # noqa: E402


class _Request:
    query_string = ""


def _ctx(cdp=None) -> CdpDiagnosticHandlerContext:
    return CdpDiagnosticHandlerContext(
        require_auth=lambda request: None,
        record_request=lambda *args, **kwargs: None,
        cors_json_response=ub._cors_json_response,
        executor=ub._EXECUTOR,
        get_cdp_module=lambda: cdp,
        log_info=lambda *args, **kwargs: None,
        log_warning=lambda *args, **kwargs: None,
        log_error=lambda *args, **kwargs: None,
    )


def _json(response):
    return ub.json.loads(response.text)


def test_cdp_diagnostic_handlers_factory_outputs():
    handlers = make_cdp_diagnostic_handlers(_ctx())
    assert callable(handlers.raw_info)
    assert callable(handlers.test_launch)
    assert callable(handlers.test_ws)


def test_cdp_diagnostic_routes_registered():
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
    assert ("GET", "/v1/browser/cdp/raw-info") in paths
    assert ("GET", "/v1/browser/cdp/test-launch") in paths
    assert ("GET", "/v1/browser/cdp/test-ws") in paths
    assert ("GET", "/v1/cdp/raw-info") in paths
    assert ("GET", "/v1/cdp/test-launch") in paths
    assert ("GET", "/v1/cdp/test-ws") in paths


def test_unified_cdp_diagnostic_handlers_bound_to_cdp_module():
    assert ub.handle_v1_cdp_raw_info.__module__ == "arena.browser.cdp.diagnostics"
    assert ub.handle_v1_cdp_test_launch.__module__ == "arena.browser.cdp.diagnostics"
    assert ub.handle_v1_cdp_test_ws.__module__ == "arena.browser.cdp.diagnostics"


def test_cdp_raw_info_missing_module():
    handler = make_cdp_diagnostic_handlers(_ctx()).raw_info
    response = asyncio.run(handler(_Request()))
    body = _json(response)
    assert response.status == 500
    assert body == {"ok": False, "error": "cdp_browser module not found"}


def test_cdp_test_launch_missing_module():
    handler = make_cdp_diagnostic_handlers(_ctx()).test_launch
    response = asyncio.run(handler(_Request()))
    body = _json(response)
    assert response.status == 500
    assert body == {"ok": False, "error": "cdp_browser module not found"}


def test_cdp_test_ws_missing_module():
    handler = make_cdp_diagnostic_handlers(_ctx()).test_ws
    response = asyncio.run(handler(_Request()))
    body = _json(response)
    assert response.status == 500
    assert body == {
        "ok": False,
        "error": "cdp_browser module not found",
        "ws_connect_ok": False,
        "tab_ws_connect_ok": False,
    }
