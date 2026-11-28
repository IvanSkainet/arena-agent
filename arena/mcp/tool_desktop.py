"""MCP desktop OCR tools via local bridge endpoints."""
from __future__ import annotations

import functools
import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from arena.jsonshape import loads_object
from arena.mcp.image_result import error_result
from arena.mcp.tool_utils import text_content

_REFUSAL_LIMIT = 64 * 1024


def bridge_refusal(exc: urllib.error.HTTPError) -> dict[str, Any]:
    """What the route answered when it refused, with the status and the route added if it did not say."""
    raw = exc.read(_REFUSAL_LIMIT + 1)  # a refusal is a few hundred bytes; anything else is not read whole
    body = raw[:_REFUSAL_LIMIT].decode("utf-8", "replace")
    answer: dict[str, Any] = {}
    try:
        answer = loads_object(body) if len(raw) <= _REFUSAL_LIMIT else {}
    except ValueError:
        pass  # not JSON: said below in words, with the start of the body
    if not answer:
        answer = {"ok": False, "error": f"the bridge answered HTTP {exc.code}", "detail": body[:500]}
        if len(raw) > _REFUSAL_LIMIT:
            answer["error"] += f" with a body over {_REFUSAL_LIMIT} bytes, which was not read"
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


def _bridge_call(ctx, path: str, payload: dict[str, Any]) -> dict[str, Any]:
    cfg = ctx.app_config() or {}
    port = int(cfg.get("port", 8765) or 8765)
    token = cfg.get("token", "")
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:  # nosec B310 -- loopback bridge URL for local MCP tool  # nosemgrep: dynamic-urllib-use-detected -- URL either loopback / fixed internal endpoint OR routed through arena.security_ssrf._validate_url (see bandit B310 nosec on the same line for the specific rationale)
        return loads_object(resp.read().decode("utf-8", "replace"))


def _bridge_get(ctx, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    cfg = ctx.app_config() or {}
    port = int(cfg.get("port", 8765) or 8765)
    token = cfg.get("token", "")
    query = ""
    if params:
        clean = {k: v for k, v in params.items() if v not in (None, "")}
        if clean:
            query = "?" + urllib.parse.urlencode(clean)
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}{query}",
        headers={"Authorization": f"Bearer {token}"},
        method="GET",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:  # nosec B310 -- loopback bridge URL for local MCP tool  # nosemgrep: dynamic-urllib-use-detected -- URL either loopback / fixed internal endpoint OR routed through arena.security_ssrf._validate_url (see bandit B310 nosec on the same line for the specific rationale)
        return loads_object(resp.read().decode("utf-8", "replace"))


@answers_refusals
def handle_desktop_tool(name: str, args: dict[str, Any], *, ctx) -> dict[str, Any] | None:
    if name == "desktop.displays":
        return text_content(json.dumps(_bridge_get(ctx, "/v1/desktop/displays"), ensure_ascii=False))
    if name == "desktop.windows":
        return text_content(json.dumps(_bridge_get(ctx, "/v1/desktop/windows", args), ensure_ascii=False))
    if name == "desktop.focus":
        return text_content(json.dumps(_bridge_call(ctx, "/v1/desktop/focus", args), ensure_ascii=False))
    if name == "desktop.window_action":
        return text_content(json.dumps(_bridge_call(ctx, "/v1/desktop/window_action", args), ensure_ascii=False))
    if name == "desktop.resolve_text_target":
        return text_content(json.dumps(_bridge_call(ctx, "/v1/desktop/resolve_text_target", args), ensure_ascii=False))
    if name == "desktop.text_action":
        return text_content(json.dumps(_bridge_call(ctx, "/v1/desktop/text_action", args), ensure_ascii=False))
    if name == "desktop.ocr":
        return text_content(json.dumps(_bridge_call(ctx, "/v1/desktop/ocr", args), ensure_ascii=False))
    if name == "desktop.find_text":
        return text_content(json.dumps(_bridge_call(ctx, "/v1/desktop/find_text", args), ensure_ascii=False))
    if name == "desktop.click_text":
        return text_content(json.dumps(_bridge_call(ctx, "/v1/desktop/click_text", args), ensure_ascii=False))
    return None
