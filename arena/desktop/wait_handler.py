"""POST /v1/desktop/wait: wait on the host for a window, a screen change or text (#621)."""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from aiohttp import web

from arena.desktop.availability import failure_response
from arena.desktop.wait import CannotLook, Looker, WaitPlan, plan_wait, wait_for
from arena.desktop.wait_looks import screen_look, text_look, window_look
from arena.desktop.window_catalog import list_desktop_windows
from arena.handler_context import DesktopHandlerContext
from arena.handler_helpers import authed, json_object_body


def _edges(region: Mapping[str, int] | None) -> dict[str, int]:
    """A region as the capture functions take it; nothing for the whole desktop."""
    return {f"region_{name}": value for name, value in (region or {}).items()}


def looker_for(ctx: DesktopHandlerContext, plan: WaitPlan) -> Looker:
    """The look for this plan, asking this bridge's own producers."""
    # No `audit_fn` on the captures: a wait is one action, and a hundred
    # looks must not write a hundred records. The handler writes one.
    tools: dict[str, Any] = {"desktop_exec": ctx.desktop_exec, "detect_env": ctx.detect_desktop_env}

    async def windows() -> dict[str, Any]:
        return await list_desktop_windows(**tools, kwin_windows_via_script=ctx.kwin_windows_via_script)

    async def capture(region: Mapping[str, int] | None) -> dict[str, Any]:
        return await ctx.capture_screenshot(fmt="png", **_edges(region), **tools)

    async def find_text(want: Any) -> dict[str, Any]:
        return await ctx.ocr_desktop(query=want["text"], min_confidence=want["min_confidence"],
                                     **_edges(want["region"]), capture_screenshot=ctx.capture_screenshot, **tools)

    if plan.kind == "window":
        return window_look(plan.want, windows, ctx.get_active_window)
    if plan.kind == "screen":
        return screen_look(plan.want, capture)
    return text_look(plan.want, find_text)


def make_desktop_wait_handler(ctx: DesktopHandlerContext):
    # Read-only, so `authed` and not `controlled`: a paused desktop may still be watched.
    @authed(ctx)
    async def handle_v1_desktop_wait(request: web.Request) -> web.Response:
        body = await json_object_body(request)
        # A request that cannot be planned raises a `BadRequest`; `authed` answers it with a 400 and does
        # not count it as an error of the bridge.
        plan = plan_wait(body)
        try:
            result = await wait_for(plan, looker_for(ctx, plan))
        except CannotLook as exc:
            return failure_response(ctx, exc.result, "the desktop could not be looked at")
        ctx.audit({"type": "desktop_wait", "for": plan.kind, "happened": result["happened"],
                   "waited_ms": result["waited_ms"], "polls": result["polls"]})
        return ctx.cors_json_response(result)

    return handle_v1_desktop_wait
