"""Structured errors and middleware extraction tests."""
import asyncio
import sys
from pathlib import Path

from aiohttp import web

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import unified_bridge as ub  # noqa: E402
from arena.errors import BridgeError, ErrorMiddlewareContext, ValidationError, make_error_middleware  # noqa: E402


class _Request(dict):
    method = "GET"
    path = "/v1/test"
    remote = "127.0.0.1"
    headers = {}


def _ctx(events=None):
    events = events if events is not None else []
    return ErrorMiddlewareContext(
        check_rate_limit_v2=lambda request: None,
        check_rate_limit=lambda request: None,
        record_request=lambda *args, **kwargs: events.append(("record", args, kwargs)),
        log_request_response=lambda *args, **kwargs: events.append(("log_request", args, kwargs)),
        cors_json_response=ub._cors_json_response,
        audit=lambda event: events.append(("audit", event)),
        log_debug=lambda *args, **kwargs: None,
        log_warning=lambda *args, **kwargs: None,
        log_error=lambda *args, **kwargs: None,
    )


def _json(response):
    return ub.json.loads(response.text)


def test_error_classes_reexported_from_errors_module():
    assert ub.BridgeError is BridgeError
    assert ub.ValidationError is ValidationError
    err = ValidationError("bad")
    assert err.http_status == 400
    assert err.to_dict() == {"ok": False, "error": "bad", "error_code": "VALIDATION_ERROR"}


def test_unified_error_middleware_bound_to_errors_module():
    assert ub.error_middleware.__module__ == "arena.errors"


def test_error_middleware_success_adds_request_id_header():
    async def handler(request):
        return web.json_response({"ok": True})

    mw = make_error_middleware(_ctx())
    response = asyncio.run(mw(_Request(), handler))
    assert response.status == 200
    assert response.headers.get("X-Request-Id")


def test_error_middleware_bridge_error_response():
    async def handler(request):
        raise ValidationError("bad input")

    events = []
    mw = make_error_middleware(_ctx(events))
    response = asyncio.run(mw(_Request(), handler))
    assert response.status == 400
    assert _json(response)["error_code"] == "VALIDATION_ERROR"
    assert any(e[0] == "record" for e in events)


def test_error_middleware_unhandled_response_and_audit():
    async def handler(request):
        raise RuntimeError("boom")

    events = []
    mw = make_error_middleware(_ctx(events))
    response = asyncio.run(mw(_Request(), handler))
    body = _json(response)
    assert response.status == 500
    assert body["error_code"] == "INTERNAL_ERROR"
    assert any(e[0] == "audit" for e in events)


# ---------------------------------------------------------------------------
# v4.41.0 -- ?token= deprecation Warning header
# ---------------------------------------------------------------------------
def test_error_middleware_adds_deprecation_warning_when_flag_set():
    """When the auth layer marks a request as having presented
    the token via ?token= (audit finding #3), the error
    middleware attaches an RFC-7234 Warning: 299 header so
    scripts and CI linters can spot the deprecation."""
    async def handler(request):
        return web.json_response({"ok": True})

    req = _Request()
    # The auth layer would normally set this; simulate it.
    req["auth_via_query_token"] = True
    response = asyncio.run(make_error_middleware(_ctx())(req, handler))
    assert response.status == 200
    assert response.headers.get("Warning", "").startswith("299"), (
        f"expected Warning: 299 header, got {response.headers.get('Warning')!r}"
    )
    assert "deprecated" in response.headers.get("Warning", "").lower()


def test_error_middleware_no_warning_when_flag_absent():
    """Header-based auth (or any request without the query-token
    flag) must not receive the deprecation Warning -- otherwise
    every request gets a spurious warning."""
    async def handler(request):
        return web.json_response({"ok": True})

    req = _Request()
    # NB: flag NOT set.
    response = asyncio.run(make_error_middleware(_ctx())(req, handler))
    assert response.headers.get("Warning") is None
