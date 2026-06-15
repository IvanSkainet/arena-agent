"""CDP page capture handlers."""
from __future__ import annotations

import asyncio
import base64 as _b64
from urllib.parse import parse_qs

from aiohttp import web

from arena.handler_context import CdpPageHandlerContext


def make_cdp_capture_handlers(ctx: CdpPageHandlerContext):
    async def handle_v1_cdp_screenshot(request):
        """GET /v1/browser/cdp/screenshot — Take screenshot.
    
        Query params:
            tab_id: string (optional)
            format: "png" | "base64" (default: "base64")
            save_path: string (optional, save to file on host)
        """
        r = ctx.require_auth(request)
        if r: return r
        ctx.record_request()
    
        qs = parse_qs(request.query_string)
        tab_id = qs.get("tab_id", [None])[0]
        fmt = qs.get("format", ["base64"])[0]
        save_path = qs.get("save_path", [None])[0]
    
        tab, err = await ctx.cdp_active_tab(tab_id)
        if err: return err
    
        try:
            # v2.3.0: Hard timeout — 18s CDP, 20s asyncio
            img_bytes = await asyncio.wait_for(tab.screenshot(path=save_path, timeout=18), timeout=20)
            if img_bytes is None:
                ctx.record_request(is_error=True, count_request=False)
                return ctx.cors_json_response({"ok": False, "error": "Screenshot returned no data"}, status=500)
        
            if fmt == "base64":
                import base64 as _b64
                b64_data = _b64.b64encode(img_bytes).decode("ascii")
                return ctx.cors_json_response({
                    "ok": True,
                    "format": "base64",
                    "data": b64_data,
                    "size_bytes": len(img_bytes),
                    "tab_id": tab.target_id,
                })
            else:
                # Return raw PNG
                return web.Response(
                    body=img_bytes,
                    content_type="image/png",
                    headers={"Access-Control-Allow-Origin": "*"}
                )
        except asyncio.TimeoutError:
            ctx.record_request(is_error=True, count_request=False)
            ctx.log_error("[CDP] screenshot timed out (20s)")
            return ctx.cors_json_response(
                {"ok": False, "error": "Screenshot timed out (20s limit)", "timeout": 20},
                status=408
            )
        except Exception as e:
            ctx.record_request(is_error=True, count_request=False)
            return ctx.cors_json_response({"ok": False, "error": str(e)}, status=500)


    async def handle_v1_cdp_dom(request):
        """GET /v1/browser/cdp/dom — Dump page DOM.
    
        Query params:
            tab_id: string (optional)
        """
        r = ctx.require_auth(request)
        if r: return r
        ctx.record_request()
    
        qs = parse_qs(request.query_string)
        tab_id = qs.get("tab_id", [None])[0]
    
        tab, err = await ctx.cdp_active_tab(tab_id)
        if err: return err
    
        try:
            # v2.3.0: Hard timeout — 18s CDP, 20s asyncio
            html = await asyncio.wait_for(tab.dump_dom(timeout=18), timeout=20)
            if html is None:
                ctx.record_request(is_error=True, count_request=False)
                return ctx.cors_json_response({"ok": False, "error": "Failed to dump DOM"}, status=500)
        
            # Truncate if too large
            max_len = ctx.default_max_output
            truncated = False
            if len(html) > max_len:
                html = html[:max_len] + f"\n...[truncated {len(html) - max_len} chars]"
                truncated = True
        
            return ctx.cors_json_response({
                "ok": True,
                "html": html,
                "length": len(html),
                "truncated": truncated,
                "tab_id": tab.target_id,
            })
        except asyncio.TimeoutError:
            ctx.record_request(is_error=True, count_request=False)
            ctx.log_error("[CDP] DOM dump timed out (20s)")
            return ctx.cors_json_response(
                {"ok": False, "error": "DOM dump timed out (20s limit)", "timeout": 20},
                status=408
            )
        except Exception as e:
            ctx.record_request(is_error=True, count_request=False)
            return ctx.cors_json_response({"ok": False, "error": str(e)}, status=500)



    return handle_v1_cdp_screenshot, handle_v1_cdp_dom
