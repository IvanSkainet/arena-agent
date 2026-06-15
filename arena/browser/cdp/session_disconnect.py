"""CDP session disconnect handler."""
from __future__ import annotations

import asyncio

from arena.handler_context import CdpSessionHandlerContext


async def stop_active_cdp_components(ctx: CdpSessionHandlerContext) -> None:
    """Stop optional network/intercept/cookie helpers before disconnecting CDP."""
    if ctx.cdp_state.get("interceptor") and ctx.cdp_state["interceptor"].active:
        await ctx.cdp_state["interceptor"].stop()
    if ctx.cdp_state.get("monitor") and ctx.cdp_state["monitor"].active:
        await ctx.cdp_state["monitor"].stop()
    if ctx.cdp_state.get("cookie_mgr") and ctx.cdp_state["cookie_mgr"].active:
        await ctx.cdp_state["cookie_mgr"].stop()


async def close_cdp_manager(ctx: CdpSessionHandlerContext) -> None:
    ctx.stop_cdp_watcher()
    if ctx.cdp_state["manager"]:
        await ctx.cdp_state["manager"].close()


def reset_disconnected_state(ctx: CdpSessionHandlerContext) -> None:
    ctx.cdp_state["manager"] = None
    ctx.cdp_state["monitor"] = None
    ctx.cdp_state["interceptor"] = None
    ctx.cdp_state["cookie_mgr"] = None
    ctx.cdp_state["connected"] = False
    ctx.cdp_state["last_disconnect_reason"] = "User disconnected"


def make_cdp_disconnect_handler(ctx: CdpSessionHandlerContext):
    async def handle_v1_cdp_disconnect(request):
        """POST /v1/browser/cdp/disconnect — Disconnect CDP session."""
        r = ctx.require_auth(request)
        if r:
            return r
        ctx.record_request()

        if not ctx.cdp_state["connected"]:
            return ctx.cors_json_response({"ok": True, "message": "Not connected"})

        if ctx.cdp_connect_lock.locked():
            return ctx.cors_json_response({"ok": False, "error": "CDP operation in progress"}, status=409)

        async with ctx.cdp_connect_lock:
            try:
                await stop_active_cdp_components(ctx)
                await close_cdp_manager(ctx)
                reset_disconnected_state(ctx)
                asyncio.create_task(ctx.emit_event("cdp_disconnect", {"reason": "User disconnected"}))
                return ctx.cors_json_response({"ok": True, "message": "CDP disconnected"})
            except Exception as e:
                ctx.record_request(is_error=True, count_request=False)
                return ctx.cors_json_response(
                    {"ok": False, "error": f"Disconnect error: {str(e)}"},
                    status=500,
                )

    return handle_v1_cdp_disconnect
