"""Tests for arena.handler_helpers -- the @authed decorator +
err_json/ok_json/parse_json_body helpers introduced in v3.92.0.

Follows the project's existing async-test style: plain ``def`` tests
call ``asyncio.run(...)`` instead of relying on pytest-asyncio.
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import MagicMock

from aiohttp import web

from arena.handler_helpers import (
    authed, public, err_json, ok_json, parse_json_body,
)


def _make_ctx(auth_ok: bool = True):
    """Build a minimal handler context lookalike."""
    def cors_json(body, status=200):
        return web.json_response(body, status=status)

    def require_auth(request):
        if auth_ok:
            return None
        return web.json_response({"ok": False, "error": "auth"}, status=401)

    return SimpleNamespace(
        require_auth=require_auth,
        cors_json_response=cors_json,
        record_request=MagicMock(),
    )


def _run(coro):
    return asyncio.run(coro)


# --- @authed ------------------------------------------------------------

def test_authed_short_circuits_when_auth_fails():
    ctx = _make_ctx(auth_ok=False)

    @authed(ctx)
    async def h(request):
        raise AssertionError("handler must not be called when auth fails")

    resp = _run(h(MagicMock()))
    assert resp.status == 401
    ctx.record_request.assert_not_called()


def test_authed_calls_handler_and_records_request():
    ctx = _make_ctx(auth_ok=True)
    calls = []

    @authed(ctx)
    async def h(request):
        calls.append(1)
        return ctx.cors_json_response({"ok": True, "x": 42})

    resp = _run(h(MagicMock()))
    assert resp.status == 200
    assert calls == [1]
    ctx.record_request.assert_called_once_with()


def test_authed_catches_exception_and_returns_500():
    ctx = _make_ctx(auth_ok=True)

    @authed(ctx)
    async def h(request):
        raise ValueError("boom")

    resp = _run(h(MagicMock()))
    assert resp.status == 500
    # record_request called twice: success accounting + error accounting.
    assert ctx.record_request.call_count == 2
    err_call = ctx.record_request.call_args_list[1]
    assert err_call.kwargs.get("is_error") is True
    assert err_call.kwargs.get("count_request") is False


def test_authed_lets_http_exceptions_through():
    """aiohttp routing raises HTTPException; must not be swallowed."""
    ctx = _make_ctx(auth_ok=True)

    @authed(ctx)
    async def h(request):
        raise web.HTTPNotFound()

    import pytest
    with pytest.raises(web.HTTPNotFound):
        _run(h(MagicMock()))


def test_public_skips_auth_but_records():
    """@public runs the handler even without a token."""
    def cors_json(body, status=200):
        return web.json_response(body, status=status)

    ctx = SimpleNamespace(
        require_auth=MagicMock(side_effect=AssertionError("must not be called")),
        cors_json_response=cors_json,
        record_request=MagicMock(),
    )

    @public(ctx)
    async def h(request):
        return ctx.cors_json_response({"ok": True, "pub": 1})

    resp = _run(h(MagicMock()))
    assert resp.status == 200
    ctx.record_request.assert_called_once()


def test_public_catches_exceptions_too():
    def cors_json(body, status=200):
        return web.json_response(body, status=status)

    ctx = SimpleNamespace(
        require_auth=MagicMock(),
        cors_json_response=cors_json,
        record_request=MagicMock(),
    )

    @public(ctx)
    async def h(request):
        raise RuntimeError("x")

    resp = _run(h(MagicMock()))
    assert resp.status == 500


# --- Response helpers ----------------------------------------------------

def test_err_json_basic():
    ctx = _make_ctx()
    resp = err_json(ctx, "bad thing")
    assert resp.status == 400
    body = resp.text
    assert '"ok": false' in body.lower() or '"ok":false' in body.lower()
    assert "bad thing" in body


def test_err_json_with_status_and_type():
    ctx = _make_ctx()
    resp = err_json(ctx, "not found", status=404, error_type="NotFound")
    assert resp.status == 404
    assert "NotFound" in resp.text


def test_err_json_with_extras():
    ctx = _make_ctx()
    resp = err_json(ctx, "x", hint="try Y", trace_id="abc123")
    assert "try Y" in resp.text
    assert "abc123" in resp.text


def test_ok_json_basic():
    ctx = _make_ctx()
    resp = ok_json(ctx, {"count": 5})
    assert resp.status == 200
    txt = resp.text
    assert '"ok": true' in txt.lower() or '"ok":true' in txt.lower()
    assert '"count": 5' in txt or '"count":5' in txt


def test_ok_json_no_payload():
    ctx = _make_ctx()
    resp = ok_json(ctx)
    assert resp.status == 200


# --- JSON body parser ----------------------------------------------------

def test_parse_json_body_returns_dict():
    ctx = _make_ctx()
    fake_req = MagicMock()
    async def _json():
        return {"a": 1}
    fake_req.json = _json
    data, err = _run(parse_json_body(fake_req, ctx))
    assert data == {"a": 1}
    assert err is None


def test_parse_json_body_rejects_non_object():
    ctx = _make_ctx()
    fake_req = MagicMock()
    async def _json():
        return [1, 2, 3]
    fake_req.json = _json
    data, err = _run(parse_json_body(fake_req, ctx))
    assert data is None
    assert err is not None
    assert err.status == 400


def test_parse_json_body_rejects_invalid_json():
    ctx = _make_ctx()
    fake_req = MagicMock()
    async def _json():
        raise ValueError("bad")
    fake_req.json = _json
    data, err = _run(parse_json_body(fake_req, ctx))
    assert data is None
    assert err is not None
    assert err.status == 400
    assert "invalid JSON" in err.text


# --- @authed(auto_record=False) — v3.94.0 -------------------------------

def test_authed_auto_record_false_skips_counter_on_happy_path():
    """v3.94.0: exec-style handlers need to control their own
    record_request() call (duration=, is_exec=, is_error=). Passing
    auto_record=False must skip the wrapper's counter increment.
    """
    ctx = _make_ctx(auth_ok=True)

    @authed(ctx, auto_record=False)
    async def h(request):
        return web.json_response({"ok": True})

    resp = _run(h(MagicMock()))
    assert resp.status == 200
    # Wrapper must NOT have counted — handler owns accounting.
    ctx.record_request.assert_not_called()


def test_authed_auto_record_false_still_enforces_auth():
    ctx = _make_ctx(auth_ok=False)

    @authed(ctx, auto_record=False)
    async def h(request):
        raise AssertionError("must not be called when auth fails")

    resp = _run(h(MagicMock()))
    assert resp.status == 401


def test_authed_auto_record_false_still_records_errors():
    """Exception path must still increment the error counter even
    when auto_record is disabled — otherwise silent handler crashes
    would go uncounted."""
    ctx = _make_ctx(auth_ok=True)

    @authed(ctx, auto_record=False)
    async def h(request):
        raise RuntimeError("boom")

    resp = _run(h(MagicMock()))
    assert resp.status == 500
    # Called once with (is_error=True, count_request=False).
    assert ctx.record_request.call_count == 1
    _, kwargs = ctx.record_request.call_args
    assert kwargs.get("is_error") is True
    assert kwargs.get("count_request") is False
