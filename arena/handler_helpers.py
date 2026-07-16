"""Shared decorators + response helpers for all v1 API handlers.

Eliminates the 103-occurrence boilerplate::

    async def handle_v1_foo(request):
        r = ctx.require_auth(request)
        if r:
            return r
        ctx.record_request()
        try:
            ...
        except Exception as e:
            ctx.record_request(is_error=True, count_request=False)
            return ctx.cors_json_response({"ok": False, "error": str(e)}, status=500)

Now handlers write only the actual work:

    @authed(ctx)
    async def handle_v1_foo(request):
        ...

The decorator does auth check, request counting, and turns
uncaught exceptions into `{ok: False, error, error_type}` JSON
with proper status codes and error accounting.

For handlers that need bespoke request accounting (e.g. exec-
style handlers that call ``record_request(duration=..., is_exec=True,
is_error=...)`` themselves), pass ``auto_record=False``. The
decorator will still enforce auth and catch stray exceptions, but
will not touch the request counter on the happy path -- the handler
does that itself.

Also provides small helpers for the most common error responses
so callers don't hand-craft the same JSON dict everywhere:

    err_json(ctx, "bad thing", status=400)
    ok_json(ctx, {"result": ...})

The design is deliberately non-magical: the underlying `require_auth`
and `record_request` are still on the context and callable directly
when a handler needs finer control (e.g. skipping auth for public
endpoints, or counting differently on partial success).
"""
from __future__ import annotations

import functools
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from aiohttp import web

_LOG = logging.getLogger(__name__)


HandlerFn = Callable[[web.Request], Awaitable[web.Response]]


def authed(
    ctx: Any,
    *,
    auto_record: bool = True,
) -> Callable[[HandlerFn], HandlerFn]:
    """Decorator: enforce auth + count request + catch stray exceptions.

    The wrapped handler runs only if ``ctx.require_auth(request)``
    returns falsy. On any uncaught exception the wrapper records an
    error request and returns a 500 with the exception type + str.

    ``auto_record`` (default ``True``) makes the wrapper call
    ``ctx.record_request()`` right after the auth check. Set it to
    ``False`` when the handler needs to do its own accounting -- e.g.
    exec-style handlers that record duration and error mode based on
    the shell command's outcome. Exception accounting (best-effort
    ``record_request(is_error=True, count_request=False)`` on stray
    exceptions) still runs regardless of ``auto_record``.

    Usage::

        @authed(ctx)
        async def handle_v1_foo(request):
            return ctx.cors_json_response({"ok": True, ...})

        @authed(ctx, auto_record=False)
        async def handle_v1_exec(request):
            # handler calls ctx.record_request(duration=..., is_exec=True)
            ...

    ``ctx`` is bound at decoration time; the returned coroutine is
    the actual aiohttp handler.
    """
    def _wrap(fn: HandlerFn) -> HandlerFn:
        @functools.wraps(fn)
        async def wrapper(request: web.Request) -> web.Response:
            r = ctx.require_auth(request)
            if r:
                return r
            if auto_record:
                ctx.record_request()
            try:
                return await fn(request)
            except web.HTTPException:
                # aiohttp routing errors — let them through unchanged.
                raise
            except Exception as e:  # noqa: BLE001
                try:
                    ctx.record_request(is_error=True, count_request=False)
                except Exception:
                    pass
                _LOG.exception("handler %s crashed", fn.__name__)
                return err_json(
                    ctx,
                    f"{type(e).__name__}: {e}",
                    status=500,
                    error_type=type(e).__name__,
                )
        return wrapper
    return _wrap


def controlled(ctx: Any) -> Callable[[HandlerFn], HandlerFn]:
    """Decorator for desktop input/window/text handlers.

    Same as :func:`authed` but also runs ``ctx.control_check()`` after
    auth passes. If the control lease is currently paused (returned
    an error dict), the handler short-circuits with a 403 carrying
    the lease info — this matches every desktop input handler's
    existing hand-coded ``ctrl_err = ctx.control_check()`` prelude.

    Introduced in v4.0.0 to eliminate the last ~10 preludes that
    combined auth + control gate. Wire-identical to the manual
    prelude::

        r = ctx.require_auth(request)
        if r:
            return r
        ctrl_err = ctx.control_check()
        if ctrl_err:
            return ctx.cors_json_response(ctrl_err, status=403)
        ctx.record_request()
    """
    def _wrap(fn: HandlerFn) -> HandlerFn:
        @functools.wraps(fn)
        async def wrapper(request: web.Request) -> web.Response:
            r = ctx.require_auth(request)
            if r:
                return r
            ctrl_err = ctx.control_check()
            if ctrl_err:
                return ctx.cors_json_response(ctrl_err, status=403)
            ctx.record_request()
            try:
                return await fn(request)
            except web.HTTPException:
                raise
            except Exception as e:  # noqa: BLE001
                try:
                    ctx.record_request(is_error=True, count_request=False)
                except Exception:
                    pass
                _LOG.exception("controlled handler %s crashed", fn.__name__)
                return err_json(
                    ctx, f"{type(e).__name__}: {e}", status=500,
                    error_type=type(e).__name__,
                )
        return wrapper
    return _wrap


def public(ctx: Any) -> Callable[[HandlerFn], HandlerFn]:
    """Same as :func:`authed` but skips the auth check.

    Use for endpoints intentionally exposed without a token
    (``/health``, ``/v1/version``, static asset routes).
    """
    def _wrap(fn: HandlerFn) -> HandlerFn:
        @functools.wraps(fn)
        async def wrapper(request: web.Request) -> web.Response:
            ctx.record_request()
            try:
                return await fn(request)
            except web.HTTPException:
                raise
            except Exception as e:  # noqa: BLE001
                try:
                    ctx.record_request(is_error=True, count_request=False)
                except Exception:
                    pass
                _LOG.exception("public handler %s crashed", fn.__name__)
                return err_json(
                    ctx, f"{type(e).__name__}: {e}", status=500,
                    error_type=type(e).__name__,
                )
        return wrapper
    return _wrap


# --- Response helpers ---------------------------------------------------

def err_json(
    ctx: Any,
    message: str,
    *,
    status: int = 400,
    error_type: str | None = None,
    **extra: Any,
) -> web.Response:
    """Shortcut for the ubiquitous ``{"ok": False, "error": "..."}``
    JSON error response. ``error_type`` is optional; when provided
    it goes on the payload so agents can distinguish auth failures
    from validation failures from server errors."""
    body: dict[str, Any] = {"ok": False, "error": message}
    if error_type:
        body["error_type"] = error_type
    if extra:
        body.update(extra)
    return ctx.cors_json_response(body, status=status)


def ok_json(ctx: Any, payload: dict | None = None, **extra: Any) -> web.Response:
    """Symmetric convenience for the success path. Adds ``ok: True``
    unless caller supplies it explicitly."""
    body: dict[str, Any] = {"ok": True}
    if payload:
        body.update(payload)
    if extra:
        body.update(extra)
    return ctx.cors_json_response(body)


async def parse_json_body(
    request: web.Request,
    ctx: Any,
) -> tuple[dict | None, web.Response | None]:
    """Parse a JSON request body, returning ``(data, err_response)``.

    When the body isn't valid JSON, ``data`` is ``None`` and the
    caller should return the error response as-is. Otherwise
    ``data`` holds the parsed dict and ``err_response`` is ``None``.

    Usage::

        data, err = await parse_json_body(request, ctx)
        if err:
            return err
        value = data.get("thing")
    """
    try:
        data = await request.json()
        if not isinstance(data, dict):
            return None, err_json(ctx, "JSON body must be an object", status=400)
        return data, None
    except Exception:
        return None, err_json(ctx, "invalid JSON body", status=400)
