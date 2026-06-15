"""CDP advanced stealth shot handler."""
from __future__ import annotations

import asyncio

from arena.browser.cdp.advanced_common import get_active_browser
from arena.handler_context import CdpAdvancedHandlerContext


def make_cdp_stealth_shot_handler(ctx: CdpAdvancedHandlerContext):
    async def handle_v1_cdp_stealth_shot(request):
        """POST /v1/browser/cdp/stealth/shot — Navigate to URL via CDP and take a screenshot.

        Uses the existing CDP connection for stealth-aware screenshots,
        similar to browser-act shot but without launching a separate browser.

        Body JSON:
            url: string (required)
            width: int (default: 1280)
            height: int (default: 720)
            full_page: bool (default: false)
            format: string ("png" or "jpeg", default: "png")
            timeout: float (default: 15s)
        """
        r = ctx.require_auth(request)
        if r: return r
        ctx.record_request()

        if not ctx.cdp_state["connected"]:
            ctx.record_request(is_error=True, count_request=False)
            return ctx.cors_json_response({"ok": False, "error": "CDP not connected"}, status=400)

        try:
            body = await request.json()
        except Exception:
            ctx.record_request(is_error=True, count_request=False)
            return ctx.cors_json_response({"ok": False, "error": "Invalid JSON body"}, status=400)

        url = body.get("url")
        if not url:
            ctx.record_request(is_error=True, count_request=False)
            return ctx.cors_json_response({"ok": False, "error": "missing 'url'"}, status=400)

        full_page = body.get("full_page", False)
        img_format = body.get("format", "png")
        timeout = body.get("timeout", 15)
        width = body.get("width", 1280)
        height = body.get("height", 720)

        browser = await get_active_browser(ctx)
        if not browser:
            ctx.record_request(is_error=True, count_request=False)
            return ctx.cors_json_response({"ok": False, "error": "No active tab connected"}, status=400)

        try:
            # Set viewport size
            await asyncio.wait_for(
                browser.send("Emulation.setDeviceMetricsOverride", {
                    "width": width, "height": height,
                    "deviceScaleFactor": 1, "mobile": False,
                }),
                timeout=5
            )

            # Navigate
            await asyncio.wait_for(browser.navigate(url, wait=True), timeout=timeout)

            # Take screenshot
            params = {"format": img_format}
            if full_page:
                params["captureBeyondViewport"] = True
            res = await asyncio.wait_for(browser.send("Page.captureScreenshot", params), timeout=15)

            if res and "result" in res and "data" in res["result"]:
                return ctx.cors_json_response({
                    "ok": True,
                    "url": url,
                    "format": img_format,
                    "data": res["result"]["data"],
                    "width": width,
                    "height": height,
                    "full_page": full_page,
                })
            else:
                ctx.record_request(is_error=True, count_request=False)
                return ctx.cors_json_response({"ok": False, "error": "Screenshot returned no data"}, status=500)

        except asyncio.TimeoutError:
            ctx.record_request(is_error=True, count_request=False)
            return ctx.cors_json_response({"ok": False, "error": f"Screenshot timed out ({timeout}s)"}, status=408)
        except Exception as e:
            ctx.record_request(is_error=True, count_request=False)
            return ctx.cors_json_response({"ok": False, "error": str(e)}, status=500)



    return handle_v1_cdp_stealth_shot
