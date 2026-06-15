"""CDP page input handlers."""
from __future__ import annotations

import asyncio

from arena.handler_context import CdpPageHandlerContext


def make_cdp_input_handlers(ctx: CdpPageHandlerContext):
    async def handle_v1_cdp_click(request):
        """POST /v1/browser/cdp/click — Click element by CSS selector or coordinates.

        Body JSON:
            selector: string (optional) — CSS selector for element click
            x: number (optional) — X coordinate for coordinate click
            y: number (optional) — Y coordinate for coordinate click
            tab_id: string (optional)

        Either 'selector' OR both 'x' and 'y' must be provided.
        Coordinate clicks use CDP Input.dispatchMouseEvent and can reach
        iframe content (e.g., reCAPTCHA) that CSS selectors cannot.

        v2.3.0: Added x/y coordinate support and 15s hard timeout.
        """
        r = ctx.require_auth(request)
        if r: return r
        ctx.record_request()

        try:
            body = await request.json()
        except Exception:
            ctx.record_request(is_error=True, count_request=False)
            return ctx.cors_json_response({"ok": False, "error": "Invalid JSON body"}, status=400)

        selector = body.get("selector")
        x = body.get("x")
        y = body.get("y")

        if not selector and (x is None or y is None):
            ctx.record_request(is_error=True, count_request=False)
            return ctx.cors_json_response(
                {"ok": False, "error": "Provide 'selector' or both 'x' and 'y' coordinates"},
                status=400
            )

        tab_id = body.get("tab_id")
        tab, err = await ctx.cdp_active_tab(tab_id)
        if err: return err

        try:
            if selector:
                # CSS selector click (existing behavior)
                clicked = await asyncio.wait_for(tab.click(selector, timeout=14), timeout=15)
                return ctx.cors_json_response({
                    "ok": True,
                    "clicked": clicked,
                    "selector": selector,
                    "mode": "selector",
                    "tab_id": tab.target_id,
                })
            else:
                # Coordinate click via CDP Input.dispatchMouseEvent
                clicked = await asyncio.wait_for(tab.click_at(float(x), float(y), timeout=14), timeout=15)
                return ctx.cors_json_response({
                    "ok": True,
                    "clicked": clicked,
                    "x": float(x),
                    "y": float(y),
                    "mode": "coordinates",
                    "tab_id": tab.target_id,
                })
        except asyncio.TimeoutError:
            ctx.record_request(is_error=True, count_request=False)
            ctx.log_error("[CDP] click timed out (15s)")
            return ctx.cors_json_response(
                {"ok": False, "error": "Click operation timed out (15s limit)", "timeout": 15},
                status=408
            )
        except Exception as e:
            ctx.record_request(is_error=True, count_request=False)
            return ctx.cors_json_response({"ok": False, "error": str(e)}, status=500)


    async def handle_v1_cdp_type(request):
        """POST /v1/browser/cdp/type — Type text into element.
    
        Body JSON:
            selector: string (required)
            text: string (required)
            tab_id: string (optional)
        """
        r = ctx.require_auth(request)
        if r: return r
        ctx.record_request()
    
        try:
            body = await request.json()
        except Exception:
            ctx.record_request(is_error=True, count_request=False)
            return ctx.cors_json_response({"ok": False, "error": "Invalid JSON body"}, status=400)
    
        selector = body.get("selector")
        text = body.get("text")
        if not selector or text is None:
            ctx.record_request(is_error=True, count_request=False)
            return ctx.cors_json_response({"ok": False, "error": "missing 'selector' or 'text' parameter"}, status=400)
    
        tab_id = body.get("tab_id")
        tab, err = await ctx.cdp_active_tab(tab_id)
        if err: return err
    
        try:
            # v2.3.0: Hard timeout — 14s CDP, 15s asyncio
            typed = await asyncio.wait_for(tab.type_text(selector, text, timeout=14), timeout=15)
            return ctx.cors_json_response({
                "ok": True,
                "typed": typed,
                "selector": selector,
                "tab_id": tab.target_id,
            })
        except asyncio.TimeoutError:
            ctx.record_request(is_error=True, count_request=False)
            ctx.log_error("[CDP] type_text timed out (15s)")
            return ctx.cors_json_response(
                {"ok": False, "error": "Type operation timed out (15s limit)", "timeout": 15},
                status=408
            )
        except Exception as e:
            ctx.record_request(is_error=True, count_request=False)
            return ctx.cors_json_response({"ok": False, "error": str(e)}, status=500)

    return handle_v1_cdp_click, handle_v1_cdp_type
