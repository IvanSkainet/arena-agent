"""A refused url has to answer 4xx, not 200 with `ok: false` inside.

The document has always promised `400` for `GET /v1/browser/head`, while the
handler factory passed every reader result straight to a 200 response, so a
url the validator blocked came back as a success with the refusal buried in
the body. Found by aikido and cubic on the #258 fuzzing gate, where
`status_code_conformance` compares the answer against the document.
"""
from __future__ import annotations

import asyncio
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from aiohttp.test_utils import make_mocked_request

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import unified_bridge as ub  # noqa: E402
from arena.browser.handlers import make_browser_fetch_handlers  # noqa: E402
from arena.handler_context import BrowserFetchHandlerContext  # noqa: E402

_EXECUTOR = ThreadPoolExecutor(max_workers=1)


def _handlers(head_sync):
    return make_browser_fetch_handlers(
        BrowserFetchHandlerContext(
            require_auth=lambda request: None,
            record_request=lambda *args, **kwargs: None,
            cors_json_response=ub._cors_json_response,
            executor=_EXECUTOR,
            browser_search_sync=lambda query, n: {"ok": True, "results": []},
            browser_read_sync=head_sync,
            browser_dump_sync=head_sync,
            browser_fetch_sync=head_sync,
            browser_head_sync=head_sync,
        )
    )


def _call(handler, query):
    request = make_mocked_request("GET", f"/v1/browser/head?{query}")
    response = asyncio.run(handler(request))
    return response.status, json.loads(response.body.decode("utf-8"))


def test_a_blocked_url_is_a_400_and_not_a_200():
    handlers = _handlers(lambda url: {"ok": False, "error": "blocked private address"})
    status, body = _call(handlers.head, "url=http://127.0.0.1/")
    assert status == 400
    assert body["ok"] is False
    assert body["error"] == "blocked private address"


def test_a_reader_that_names_its_own_status_keeps_it():
    handlers = _handlers(lambda url: {"ok": False, "error": "nope", "status": 403})
    status, _ = _call(handlers.head, "url=http://example.com/")
    assert status == 403


def test_a_successful_read_is_still_a_200():
    handlers = _handlers(lambda url: {"ok": True, "url": url, "status_code": 204})
    status, body = _call(handlers.head, "url=http://example.com/")
    assert status == 200
    assert body["status_code"] == 204


def test_every_url_reading_route_agrees_on_this():
    """read, dump and fetch share the factory, so they share the fix."""
    handlers = _handlers(lambda url: {"ok": False, "error": "blocked"})
    for handler in (handlers.read, handlers.dump, handlers.fetch, handlers.head):
        status, _ = _call(handler, "url=http://127.0.0.1/")
        assert status == 400


def test_a_missing_url_is_still_a_400():
    handlers = _handlers(lambda url: {"ok": True})
    status, body = _call(handlers.head, "")
    assert status == 400
    assert body["error"] == "missing url parameter"
