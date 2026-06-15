"""CDP session connect handler."""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from arena.browser.cdp.session_diagnostics import (
    build_connect_timeout_error,
    collect_connect_timeout_diagnostics,
    terminate_browser_proc,
)
from arena.handler_context import CdpSessionHandlerContext


async def parse_connect_body(request) -> tuple[int, bool]:
    """Parse optional connect body while preserving historical defaults."""
    port = 9222
    headless = True
    try:
        body = await request.json()
        port = body.get("port", 9222)
        headless = body.get("headless", True)
    except Exception:
        pass
    return port, headless


def already_connected_response(ctx: CdpSessionHandlerContext):
    return ctx.cors_json_response({
        "ok": True,
        "message": "Already connected",
        "port": ctx.cdp_state["port"],
        "tab_count": ctx.cdp_state["manager"].tab_count if ctx.cdp_state["manager"] else 0,
    })


async def retry_active_tab_connection(ctx: CdpSessionHandlerContext, mgr, port: int) -> bool:
    """Verify/retry active tab connection after manager.connect()."""
    active_tab = mgr.active_tab
    tab_connected = active_tab is not None and active_tab.connected
    if active_tab and not active_tab.connected:
        try:
            await asyncio.wait_for(active_tab.connect(), timeout=25)
            tab_connected = True
            ctx.log_info("[CDP] Re-connected active tab %s on second attempt", mgr.active_tab_id)
        except Exception as e:
            ctx.log_warning("[CDP] Active tab auto-connect retry 1 failed: %s", e)

        if not tab_connected:
            old_url = active_tab.ws_url
            new_url = f"ws://127.0.0.1:{port}/devtools/page/{active_tab.target_id}"
            if new_url != old_url:
                ctx.log_info("[CDP] Retrying with constructed WS URL: %s (was: %s)", new_url, old_url[:60])
                active_tab.ws_url = new_url
                try:
                    await asyncio.wait_for(active_tab.connect(), timeout=15)
                    tab_connected = True
                    ctx.log_info("[CDP] Connected active tab with constructed WS URL")
                except Exception as e:
                    ctx.log_warning("[CDP] Constructed WS URL retry failed: %s", e)
                    active_tab.ws_url = old_url
    return tab_connected


def store_connected_state(ctx: CdpSessionHandlerContext, mgr, *, port: int, headless: bool) -> None:
    ctx.cdp_state["manager"] = mgr
    ctx.cdp_state["connected"] = True
    ctx.cdp_state["port"] = port
    ctx.cdp_state["headless"] = headless
    ctx.cdp_state["last_connect_time"] = datetime.now(timezone.utc).isoformat()
    ctx.cdp_state["last_disconnect_reason"] = None


def connected_response(ctx: CdpSessionHandlerContext, mgr, *, port: int, headless: bool, tab_connected: bool):
    result = {
        "ok": True,
        "message": "CDP connected",
        "port": port,
        "headless": headless,
        "tab_count": mgr.tab_count,
        "active_tab_id": mgr.active_tab_id,
        "tabs": [tab.to_dict() for tab in mgr.list_tabs()],
        "ws_diagnostics": mgr.ws_diagnostics,
    }
    if not tab_connected:
        result["warning"] = "Active tab is not connected — CDP page operations may fail. Try reconnecting."
    return ctx.cors_json_response(result)


def timeout_response(ctx: CdpSessionHandlerContext, mgr):
    browser_crashed, launch_diag, stderr = collect_connect_timeout_diagnostics(mgr)
    error_msg = build_connect_timeout_error(
        mgr,
        browser_crashed=browser_crashed,
        launch_diag=launch_diag,
        stderr=stderr,
    )
    terminate_browser_proc(mgr)
    return ctx.cors_json_response(
        {
            "ok": False,
            "error": error_msg,
            "browser_crashed": browser_crashed,
            "diagnostics": launch_diag,
            "stderr": stderr[:1500],
        },
        status=408,
    )


def make_cdp_connect_handler(ctx: CdpSessionHandlerContext):
    async def handle_v1_cdp_connect(request):
        """POST /v1/browser/cdp/connect — Connect to browser CDP."""
        r = ctx.require_auth(request)
        if r:
            return r
        ctx.record_request()

        cdp = ctx.get_cdp_module()
        if not cdp:
            ctx.record_request(is_error=True, count_request=False)
            return ctx.cors_json_response(
                {"ok": False, "error": "cdp_browser module not found. Install to scripts/ directory."},
                status=500,
            )

        if ctx.cdp_state["connected"]:
            return already_connected_response(ctx)

        if ctx.cdp_connect_lock.locked():
            return ctx.cors_json_response({"ok": False, "error": "CDP connect already in progress"}, status=409)

        port, headless = await parse_connect_body(request)

        async with ctx.cdp_connect_lock:
            try:
                mgr = cdp.CDPTabManager(port=port, headless=headless, auto_launch=True)
                try:
                    await asyncio.wait_for(mgr.connect(), timeout=60)
                except asyncio.TimeoutError:
                    ctx.record_request(is_error=True, count_request=False)
                    return timeout_response(ctx, mgr)

                store_connected_state(ctx, mgr, port=port, headless=headless)
                asyncio.create_task(ctx.emit_event("cdp_connect", {"port": port, "headless": headless}))
                ctx.start_cdp_watcher()

                tab_connected = await retry_active_tab_connection(ctx, mgr, port)
                return connected_response(ctx, mgr, port=port, headless=headless, tab_connected=tab_connected)
            except Exception as e:
                ctx.record_request(is_error=True, count_request=False)
                return ctx.cors_json_response(
                    {"ok": False, "error": f"Failed to connect: {str(e)}"},
                    status=500,
                )

    return handle_v1_cdp_connect
