"""Browser fetch handler factory smoke tests."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import unified_bridge as ub  # noqa: E402
from arena.handler_context import BrowserFetchHandlerContext  # noqa: E402
from arena.browser.handlers import make_browser_fetch_handlers  # noqa: E402


def test_browser_fetch_handlers_factory_outputs():
    ctx = BrowserFetchHandlerContext(
        require_auth=ub.require_auth,
        record_request=ub._record_request,
        cors_json_response=ub._cors_json_response,
        executor=ub._EXECUTOR,
        browser_search_sync=ub._browser_search_sync,
        browser_read_sync=ub._browser_read_sync,
        browser_dump_sync=ub._browser_dump_sync,
        browser_fetch_sync=ub._browser_fetch_sync,
        browser_head_sync=ub._browser_head_sync,
    )
    handlers = make_browser_fetch_handlers(ctx)
    assert callable(handlers.search)
    assert callable(handlers.read)
    assert callable(handlers.dump)
    assert callable(handlers.fetch)
    assert callable(handlers.head)


def test_unified_routes_use_extracted_browser_fetch_handlers():
    app = ub.make_app({"token": "test"})
    paths = {(r.method, r.resource.get_info().get("path") or r.resource.get_info().get("formatter")) for r in app.router.routes()}
    for path in ["/v1/browser/search", "/v1/browser/read", "/v1/browser/dump", "/v1/browser/fetch", "/v1/browser/head"]:
        assert ("GET", path) in paths
