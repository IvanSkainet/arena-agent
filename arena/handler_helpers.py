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


# StreamResponse, not Response: aiohttp's own handler contract is
# `-> StreamResponse`, and several handlers here legitimately return a
# FileResponse / streamed NDJSON tail, which are StreamResponse subclasses but
# not Response. Narrowing this alias to Response rejected those handlers.
HandlerFn = Callable[[web.Request], Awaitable[web.StreamResponse]]

# "the body could not be read as JSON at all", distinct from any JSON value
# a caller might legitimately have sent -- including None.
_UNREADABLE = object()


class BadRequest(ValueError):
    """Base for the caller mistakes the decorators below answer with a 400.

    A handler raises one of these instead of returning a response, so the
    refusal is written once, in the wrapper, rather than copy-pasted at every
    call site -- which is how the copies drifted apart in the first place
    (#254, #259).

    Subclassing ``ValueError`` is deliberate: a handler that already wrote
    ``except ValueError:`` around its own parsing keeps the behaviour it has
    today when it adopts one of these helpers.
    """

    #: Extra machine-readable fields for the error envelope.
    details: dict[str, Any] = {}


class QueryParamError(BadRequest):
    """A query parameter was present but could not be parsed (#254).

    Raised by :func:`query_int`. The handler decorators in this module
    translate it into a 400 naming the parameter, instead of letting it
    reach the generic ``except Exception`` and become a 500.

    Carries the parameter *name*, not the offending value: the name is the
    part of the pair the caller has to fix, and echoing an attacker-supplied
    value back into a response body turns a JSON error envelope into a
    reflection gadget.
    """

    def __init__(self, param: str) -> None:
        self.param = param
        self.details = {"param": param}
        super().__init__(f"query parameter {param!r} must be an integer")


# Every JSON type `json.loads` can produce except the object we wanted.
# The document repeats this list as an enum, and a test compares the two.
_JSON_TYPE_NAMES: dict[type, str] = {
    type(None): "null", bool: "boolean", int: "number",
    float: "number", str: "string", list: "array",
}


class JsonBodyError(BadRequest):
    """The request body is not the JSON object this endpoint reads (#259).

    Names the JSON *type* that arrived, never the value. The type is one of
    five fixed words and tells the caller exactly what to change; the value
    is attacker-controlled text that has no business being reflected back
    out of an error envelope, into a log line or onto a dashboard.

    `received` is absent in two cases, which is why the document marks it
    optional: when nothing parsed at all -- there is no JSON type to name,
    and inventing `null` would tell a client the body was JSON null when it
    was truncated bytes -- and when a custom decoder produced something
    outside the five. The second is unreachable through `json.loads` and is
    handled rather than asserted, because a 500 from an error path is a
    poor way to find out otherwise.
    """

    def __init__(self, received: object = _UNREADABLE) -> None:
        if received is _UNREADABLE:
            self.received = None
            super().__init__("request body must be valid JSON")
            return
        self.received = _JSON_TYPE_NAMES.get(type(received))
        if self.received is None:
            super().__init__("request body must be a JSON object")
            return
        self.details = {"received": self.received}
        super().__init__(
            f"request body must be a JSON object, received {self.received}")


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
# v4.44.0: safe numeric parsing for HTTP handler inputs
# ---------------------------------------------------------------------------

# Sentinel for "no default requested; raise ValueError on bad input".
_NO_DEFAULT = object()


def safe_float(
    value: Any,
    *,
    default: float | object = _NO_DEFAULT,
    minimum: float | None = None,
    maximum: float | None = None,
) -> float:
    """Parse a caller-supplied value into a bounded, finite float.

    v4.44.0 security-hardening helper. Every HTTP handler that
    coerces a query-string or JSON-body value into ``float`` used
    to be a copy of::

        try:
            x = float(request.query.get("timeout", "1.5"))
        except (TypeError, ValueError):
            x = 1.5

    That pattern is unsafe against two attacker-controlled shapes
    that semgrep (``nan-injection``) rightly complains about:

    * ``float("nan")`` -- passes through
      ``try/except (TypeError, ValueError)`` because ``NaN`` is a
      valid float. Downstream comparisons (``if x >= 0``) return
      ``False`` for both branches, so guard clauses relying on
      ordering silently break. In our case
      ``socket.settimeout(nan)`` raises ``ValueError`` server-side
      and turns a benign probe into a 500, which is a small
      availability hit -- but nan-in-comparison bugs elsewhere
      could bypass upper bounds.
    * ``float("inf")`` -- similar. Passes the ``try/except`` and
      then either loops forever, raises deep inside a syscall
      (``ValueError: timestamp out of range for platform time_t``),
      or converts to an overflow later.

    The safe pattern is: parse, reject NaN/Inf, optionally clamp
    to a ``[minimum, maximum]`` range. Everything else falls back
    to the caller-supplied default (or raises ``ValueError`` if
    the caller wanted strict).

    Args:
      value: any input, typically a query-string value.
      default: value to return on parse failure. Omit to make the
        function raise ``ValueError`` on any bad input.
      minimum, maximum: inclusive bounds. Out-of-range values are
        clamped when a ``default`` is provided; otherwise raise.

    Returns:
      A finite float, either the parsed value clamped into
      ``[minimum, maximum]`` or ``default``.
    """
    try:
        x = float(value)
    except (TypeError, ValueError):
        if default is _NO_DEFAULT:
            raise
        return default  # type: ignore[return-value]
    # NaN and +/-Inf are both "valid floats" per Python's float()
    # but almost never what an HTTP caller legitimately means.
    # Reject both.
    if x != x or x in (float("inf"), float("-inf")):
        if default is _NO_DEFAULT:
            raise ValueError(f"non-finite float rejected: {value!r}")
        return default  # type: ignore[return-value]
    if minimum is not None and x < minimum:
        if default is _NO_DEFAULT:
            raise ValueError(f"below minimum {minimum}: {x}")
        # Clamp to the boundary rather than falling to the default;
        # a request for "timeout=0.001" against min=0.01 is closer
        # to "operator meant fast" than "operator meant default".
        return float(minimum)
    if maximum is not None and x > maximum:
        if default is _NO_DEFAULT:
            raise ValueError(f"above maximum {maximum}: {x}")
        return float(maximum)
    return x


def safe_int(
    value: Any,
    *,
    default: int | object = _NO_DEFAULT,
    minimum: int | None = None,
    maximum: int | None = None,
) -> int:
    """Parse a caller-supplied value into a bounded int.

    v4.44.0 companion to :func:`safe_float`. Same clamp/default
    semantics. Not vulnerable to NaN/Inf (Python's ``int()`` rejects
    both), but still worth centralising because HTTP inputs also
    like to send negative "timeout" or "limit" values that break
    downstream ``range()`` / ``head[:n]`` slicing invariants.
    """
    try:
        x = int(value)
    except (TypeError, ValueError):
        if default is _NO_DEFAULT:
            raise
        return default  # type: ignore[return-value]
    if minimum is not None and x < minimum:
        if default is _NO_DEFAULT:
            raise ValueError(f"below minimum {minimum}: {x}")
        return int(minimum)
    if maximum is not None and x > maximum:
        if default is _NO_DEFAULT:
            raise ValueError(f"above maximum {maximum}: {x}")
        return int(maximum)
    return x


def query_int(
    request: web.Request, name: str, *, default: int | None,
) -> int | None:
    """Read an integer query parameter, or refuse the request with a 400.

    ``safe_int`` (v4.44.0) already did the parsing. What it could not decide
    is what a *handler* should do with a bad value, and both of the answers
    it offers are wrong on their own:

    * ``safe_int(raw, default=50)`` swallows the mistake. A client sending
      ``?limit=fifty`` gets 200 and the first fifty rows, and goes on sending
      ``fifty`` forever because nothing ever told it otherwise.
    * ``safe_int(raw)`` raises ``ValueError``, which the wrappers above turn
      into ``500 {"error": "ValueError: invalid literal for int() ...",
      "error_type": "ValueError"}`` -- the bridge blaming itself for the
      caller's typo, and naming an internal Python class while doing it.
      That is #254, measured live on the operator's bridge at v4.170.0.

    So: parse strictly, and re-raise the failure as :class:`QueryParamError`,
    which the decorators answer with 400.

    A missing or empty parameter is not an error. ``?offset=`` means
    "unspecified" and yields ``default``, which is what it did before -- the
    old ``int(query.get("offset", [0])[0] or 0)`` reached ``int()`` only for
    a non-empty value too. Only the parse verdict changes, never the value
    of a request that already worked.

    Deliberately no ``minimum``/``maximum``: every current caller passes its
    bad values on to a layer that already clamps them (``?limit=-1`` answers
    200 with ``limit: 1`` today), and turning those into refusals would be a
    behaviour change riding along with a bug fix. ``safe_int`` still has the
    bounds for callers that genuinely need them.

    Args:
      request: the live aiohttp request.
      name: query-string key, named in the error so the caller can fix it.
      default: value for a missing or empty parameter. Keyword-only and
        required -- pass ``None`` for a genuinely optional one, so that
        "I forgot a default" cannot pass for "there is none".

    Raises:
      QueryParamError: the parameter was supplied and does not parse.
    """
    raw = request.query.get(name)
    if raw is None or raw == "":
        return default
    try:
        return safe_int(raw)
    except (TypeError, ValueError):
        raise QueryParamError(name) from None


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
    try:
        data = await request.json()
    except Exception:
        raise JsonBodyError() from None
    if not isinstance(data, dict):
        raise JsonBodyError(data)
    return data
