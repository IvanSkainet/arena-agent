"""v4.0.0 tests for the @controlled decorator + desktop migration.

@controlled combines auth + control-lease check + record_request +
exception→500 wrapper, replacing the ~10 hand-crafted `ctrl_err =
ctx.control_check()` preludes across the desktop handlers.
"""
from __future__ import annotations

import asyncio
import inspect
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from aiohttp import web  # noqa: E402

from arena.handler_helpers import controlled  # noqa: E402


def _make_ctx(*, auth_ok: bool = True, control_locked: bool = False):
    def cors_json(body, status=200):
        return web.json_response(body, status=status)

    def require_auth(request):
        return None if auth_ok else cors_json({"ok": False}, status=401)

    def control_check():
        if control_locked:
            return {"ok": False, "error": "control_paused", "status": "paused"}
        return None

    return SimpleNamespace(
        require_auth=require_auth,
        control_check=control_check,
        cors_json_response=cors_json,
        record_request=MagicMock(),
    )


def _run(coro):
    return asyncio.run(coro)


def test_controlled_calls_handler_and_records_request():
    ctx = _make_ctx()

    @controlled(ctx)
    async def h(request):
        return web.json_response({"ok": True})

    resp = _run(h(MagicMock()))
    assert resp.status == 200
    ctx.record_request.assert_called_once()


def test_controlled_short_circuits_on_auth_failure():
    ctx = _make_ctx(auth_ok=False)

    @controlled(ctx)
    async def h(request):
        raise AssertionError("handler must not run when auth fails")

    resp = _run(h(MagicMock()))
    assert resp.status == 401


def test_controlled_short_circuits_on_control_lock():
    ctx = _make_ctx(control_locked=True)

    @controlled(ctx)
    async def h(request):
        raise AssertionError("handler must not run when control is paused")

    resp = _run(h(MagicMock()))
    assert resp.status == 403
    ctx.record_request.assert_not_called()


def test_controlled_captures_exception_as_500():
    ctx = _make_ctx()

    @controlled(ctx)
    async def h(request):
        raise RuntimeError("boom")

    resp = _run(h(MagicMock()))
    assert resp.status == 500
    # record_request called twice: once on entry, once for error.
    assert ctx.record_request.call_count == 2


# --- v4.0.0 migration regression guards ---------------------------------

def test_desktop_modules_use_controlled_decorator():
    """Every desktop input/window/ocr/text handler wraps through
    the shared @controlled decorator."""
    from arena.desktop import (
        input_handlers as _ih,
        window_handlers as _wh,
        ocr_handler as _oh,
        text_action_handler as _ta,
        window_action_handler as _wa,
    )
    for mod in (_ih, _wh, _oh, _ta, _wa):
        src = inspect.getsource(mod)
        assert "@controlled(ctx)" in src, (
            f"{mod.__name__} does not use @controlled — v4.0.0 migrated "
            f"all desktop control-lease handlers to the shared decorator."
        )
        assert "from arena.handler_helpers import" in src, (
            f"{mod.__name__} does not import from arena.handler_helpers."
        )


def test_desktop_modules_free_of_manual_control_prelude():
    """The inline ``ctrl_err = ctx.control_check(); if ctrl_err: ...``
    prelude is gone from every desktop control-lease handler module."""
    from arena.desktop import (
        input_handlers as _ih,
        window_handlers as _wh,
        ocr_handler as _oh,
        text_action_handler as _ta,
        window_action_handler as _wa,
    )
    for mod in (_ih, _wh, _oh, _ta, _wa):
        src = inspect.getsource(mod)
        assert "ctrl_err = ctx.control_check()" not in src, (
            f"{mod.__name__} still contains the inline control-check "
            f"prelude — v4.0.0 migrated it to @controlled."
        )
