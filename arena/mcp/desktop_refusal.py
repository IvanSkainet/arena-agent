"""What a desktop MCP tool returns when its bridge route refuses (#620)."""
from __future__ import annotations

import functools
import urllib.error
import urllib.parse
from typing import Any

from arena.jsonshape import loads_object
from arena.mcp.image_result import error_result

REFUSAL_LIMIT = 64 * 1024


def _said(raw: bytes) -> dict[str, Any]:
    """The JSON object in a refusal body, or nothing when it is not one or was not read whole."""
    if len(raw) > REFUSAL_LIMIT:
        return {}
    try:
        return loads_object(raw.decode("utf-8", "replace"))
    except ValueError:
        return {}  # not JSON: the caller says so in words, with the start of the body


def bridge_refusal(exc: urllib.error.HTTPError) -> dict[str, Any]:
    """What the route answered when it refused, with the status and the route added if it did not say."""
    raw = exc.read(REFUSAL_LIMIT + 1)  # a refusal is a few hundred bytes; anything else is not read whole
    answer: dict[str, Any] = _said(raw)
    if not answer:
        answer = {"error": f"the bridge answered HTTP {exc.code}", "detail": raw[:500].decode("utf-8", "replace")}
        if len(raw) > REFUSAL_LIMIT:
            answer["error"] += f" with a body over {REFUSAL_LIMIT} bytes, which was not read"
    answer.setdefault("ok", False)
    answer.setdefault("status", exc.code)
    # A tool such as desktop_app.click_window makes several calls; this says which one refused.
    answer.setdefault("route", urllib.parse.urlsplit(exc.url or "").path)
    return answer


def answers_refusals(handler):
    """Wrap a desktop tool dispatcher so a refusing route is reported in the route's own words (#620)."""
    # The helpers below let HTTPError escape, and the generic MCP handler turned
    # it into "ERROR: HTTPError: HTTP Error 503: Service Unavailable": the reason
    # the route gave, and the list of tools it was missing, never reached the agent.
    @functools.wraps(handler)
    def answering(name: str, args: dict[str, Any], *, ctx) -> dict[str, Any] | None:
        try:
            return handler(name, args, ctx=ctx)
        except urllib.error.HTTPError as exc:
            return error_result(bridge_refusal(exc))
    return answering
