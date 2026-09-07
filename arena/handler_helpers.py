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

# Re-exported under their original names: every call site imported these
# from here before they moved to their own module (#266), and the `X as X`
# form is what tells the linters the re-export is deliberate.
from arena.handler_errors import (
    _JSON_TYPE_NAMES as _JSON_TYPE_NAMES,
    _UNREADABLE as _UNREADABLE,
    BadRequest as BadRequest,
    BodyFieldError as BodyFieldError,
    JsonBodyError as JsonBodyError,
    QueryParamError as QueryParamError,
)

_LOG = logging.getLogger(__name__)


# StreamResponse, not Response: aiohttp's own handler contract is
# `-> StreamResponse`, and several handlers here legitimately return a
# FileResponse / streamed NDJSON tail, which are StreamResponse subclasses but
# not Response. Narrowing this alias to Response rejected those handlers.
HandlerFn = Callable[[web.Request], Awaitable[web.StreamResponse]]

def bad_request_refusal(ctx: Any, error: BadRequest) -> web.Response:
    """Turn a :class:`BadRequest` into the 400 the caller deserves.

    400, not 500: the request was malformed, and a 500 tells a retrying
    client that waiting might help. No ``error_type``: every other 400 in
    this codebase omits it, and the field has only ever carried a Python
    class name, which is an implementation detail the caller cannot act on.
    ``details`` carries the machine-readable part -- which parameter, which
    JSON type -- so a client does not have to parse English.

    Deliberately does *not* call ``record_request(is_error=True)``. The
    error counter feeds the health snapshot, and a caller sending
    ``?limit=null`` is not the bridge being unhealthy.
    """
    return err_json(ctx, str(error), status=400, **error.details)


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
        async def wrapper(request: web.Request) -> web.StreamResponse:
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
            except BadRequest as e:
                return bad_request_refusal(ctx, e)
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
        async def wrapper(request: web.Request) -> web.StreamResponse:
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
            except BadRequest as e:
                return bad_request_refusal(ctx, e)
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
        async def wrapper(request: web.Request) -> web.StreamResponse:
            ctx.record_request()
            try:
                return await fn(request)
            except web.HTTPException:
                raise
            except BadRequest as e:
                return bad_request_refusal(ctx, e)
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
) -> tuple[dict, None] | tuple[None, web.Response]:
    """Parse a JSON request body, returning ``(data, err_response)``.

    When the body isn't valid JSON, ``data`` is ``None`` and the
    caller should return the error response as-is. Otherwise
    ``data`` holds the parsed dict and ``err_response`` is ``None``.

    The return type is a union of two tuples rather than
    ``tuple[dict | None, Response | None]``: the two states are mutually
    exclusive, so a caller that has checked the error holds a real dict.

    Honest caveat, measured rather than assumed: pyrefly 1.2.0 does *not*
    yet benefit from this. It reads the signature correctly, but the moment
    the result is unpacked (``data, err = await ...``) it collapses the union
    to ``dict | None`` and loses the correlation between the two elements --
    confirmed with ``reveal_type``. Indexing the tuple instead of unpacking
    preserves it, but rewriting 49 handlers into a less readable style to
    please a checker is the wrong trade. The signature stays because it
    describes the function accurately; the ~90 ``.get`` findings it should
    have removed remain in the debt count until the checker catches up.

    Usage::

        data, err = await parse_json_body(request, ctx)
        if err:
            return err
        value = data.get("thing")

    Since #259 this is a thin adapter over :func:`json_object_body`, which
    is where the check now lives, so both spellings refuse a non-object body
    in exactly the same words. New handlers should raise rather than unpack:
    the decorator turns it into the response and the call site stays one
    line. This form remains for the ~49 handlers already written against it.
    """
    try:
        return await json_object_body(request), None
    except BadRequest as e:
        return None, bad_request_refusal(ctx, e)


# ---------------------------------------------------------------------------
# v4.44.0: safe numeric parsing for HTTP handler inputs. The parsers moved to
# `safe_numeric` in #270 -- `handler_params` needs them and this module
# re-exports `handler_params`, so leaving them here made importing either one
# first a coin toss. Re-exported so no call site had to move.
# ---------------------------------------------------------------------------
# Re-exported so that `from arena.handler_helpers import query_int` keeps
# working: the parameter readers moved to `handler_params` when this module
# hit the 600-line ceiling, and rewriting forty call sites for a file split
# would be churn with no defect behind it (#266, #270).
#
# Down here rather than at the top because `handler_params` re-exports back
# into this module. E402 is suppressed with a bare code: SonarCloud's S7632
# reads trailing prose in a `noqa` as a malformed suppression, which it is.
from arena.handler_params import (  # noqa: E402
    body_int as body_int,
    query_int as query_int,
)
from arena.safe_numeric import (  # noqa: E402
    safe_float as safe_float,
    safe_int as safe_int,
)


async def json_object_body(
    request: web.Request, *, allow_empty: bool = False,
) -> dict:
    """Read the request body as a JSON object, or refuse the request with 400.

    ``parse_json_body`` already existed and already made the isinstance
    check. Twenty-four documented write operations did not call it; each had
    hand-written::

        try:
            data = await request.json()
        except Exception as e:
            return ...400...

    which catches a *parse* failure and then hands a ``bool`` straight to
    ``data.get`` -- ``500 {"error": "AttributeError: 'bool' object has no
    attribute 'get'", "error_type": "AttributeError"}``. That is #259, and it
    is the same shape as #254: the helper exists, the call sites predate it.

    Raising rather than returning ``(value, error)`` is what makes adoption a
    one-line change instead of a four-line one, and it is why the copies
    cannot drift again: the refusal lives in the decorator.

    Args:
      request: the live aiohttp request.
      allow_empty: treat *no body at all* as ``{}``. For endpoints where
        every field is optional, so ``POST`` with no body is a real request
        rather than a mistake. An empty body is still not a JSON object,
        so this has to be asked for explicitly.

    Raises:
      JsonBodyError: the body is not readable as JSON, or is JSON but not an
        object.
    """
    if allow_empty and not request.can_read_body:
        return {}
    data = await _read_json(request)
    if not isinstance(data, dict):
        raise JsonBodyError(data)
    return data


async def _read_json(request: web.Request) -> Any:
    """Parse the body, keeping the two failures apart.

    Split out of `json_object_body` because the two `except` clauses put it
    on CodeScene's complexity threshold, and because the distinction is
    worth a name: aiohttp raises 413 here when the body is over
    `client_max_size`, and flattening that into a 400 tells the caller to
    fix syntax when the answer is to send less. All nineteen copies this
    helper replaced got that wrong too.
    """
    try:
        return await request.json()
    except web.HTTPException:
        raise
    except Exception:
        raise JsonBodyError() from None
