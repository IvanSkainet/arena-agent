"""CDP page nav handler."""
from __future__ import annotations

import asyncio
import time

from arena.handler_context import CdpPageHandlerContext
from arena.handler_helpers import authed, err_json


def make_cdp_navigate_handler(ctx: CdpPageHandlerContext):
    @authed(ctx)
    async def handle_v1_cdp_navigate(request):
        """POST /v1/browser/cdp/navigate — Navigate to URL.

        Body JSON:
            url: string (required)
            tab_id: string (optional, uses active tab if not specified)
            wait: bool (default: true)

        v2.4.0: Increased timeout to 30s. After navigation, auto-refreshes
        the tab list and activates the correct tab (fixes tab-switching bug
        where navigation created a new tab and CDP lost connection).
        """

        try:
            body = await request.json()
        except Exception:
            ctx.record_request(is_error=True, count_request=False)
            return ctx.cors_json_response({"ok": False, "error": "Invalid JSON body"}, status=400)

        url = body.get("url")
        if not url:
            ctx.record_request(is_error=True, count_request=False)
            return ctx.cors_json_response({"ok": False, "error": "missing 'url' parameter"}, status=400)

        tab_id = body.get("tab_id")
        wait = body.get("wait", True)

        tab, err = await ctx.cdp_active_tab(tab_id)
        if err: return err
        # Track navigation time so watcher skips probes during page loads
        ctx.cdp_state["last_navigation_time"] = time.time()

        original_tab_id = tab.target_id
        try:
            # v2.4.0: Hard timeout — 28s CDP, 30s asyncio (increased from 20s for heavy sites)
            result = await asyncio.wait_for(tab.navigate(url, wait=wait, timeout=28), timeout=30)

            # v2.4.0: Auto-refresh tab list after navigation
            # Navigation may have created a new tab or changed the active one
            mgr = ctx.cdp_state.get("manager")
            if mgr:
                try:
                    await mgr.sync_tabs()
                except Exception as e:
                    ctx.log_debug("[CDP] Tab sync after navigate failed (non-fatal): %s", e)

            return ctx.cors_json_response({
                "ok": True,
                "url": url,
                "tab_id": tab.target_id,
                "result": result,
            })
        except asyncio.TimeoutError:
            ctx.record_request(is_error=True, count_request=False)
            ctx.log_error("[CDP] navigate timed out (30s) for URL: %.200s", url)
            return ctx.cors_json_response(
                {"ok": False, "error": f"Navigation timed out (30s limit): {url}", "timeout": 30},
                status=408
            )
        except Exception as e:
            ctx.record_request(is_error=True, count_request=False)
            return ctx.cors_json_response(
                {"ok": False, "error": str(e)},
                status=500
            )



    return handle_v1_cdp_navigate
