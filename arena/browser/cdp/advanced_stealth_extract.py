"""CDP advanced stealth extract handler."""
from __future__ import annotations

import asyncio
import json

from arena.browser.cdp.advanced_common import get_active_browser
from arena.handler_context import CdpAdvancedHandlerContext


def make_cdp_stealth_extract_handler(ctx: CdpAdvancedHandlerContext):
    async def handle_v1_cdp_stealth_extract(request):
        """POST /v1/browser/cdp/stealth/extract — Navigate to URL via CDP and extract page content.

        Uses the existing CDP connection for stealth-aware content extraction,
        similar to browser-act extract but without launching a separate browser.

        Body JSON:
            url: string (required)
            wait_for: string (optional CSS selector to wait for)
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

        wait_for = body.get("wait_for")
        timeout = body.get("timeout", 15)

        browser = await get_active_browser(ctx)
        if not browser:
            ctx.record_request(is_error=True, count_request=False)
            return ctx.cors_json_response({"ok": False, "error": "No active tab connected"}, status=400)

        try:
            # Navigate to the URL
            await asyncio.wait_for(browser.navigate(url, wait=True), timeout=timeout)

            # Wait for specific element if requested
            if wait_for:
                safe_selector = json.dumps(wait_for)
                expr = f"new Promise((resolve, reject) => {{ const check = () => {{ if (document.querySelector({safe_selector})) resolve(true); else setTimeout(check, 200); }}; setTimeout(() => reject('timeout'), {(timeout-2)*1000}); check(); }})"
                await asyncio.wait_for(
                    browser.eval_js(expr),
                    timeout=timeout
                )

            # Extract content
            html = await asyncio.wait_for(browser.dump_dom(), timeout=10)
            title = await asyncio.wait_for(browser.eval_js("document.title"), timeout=5)
            current_url = await asyncio.wait_for(browser.eval_js("window.location.href"), timeout=5)

            # Extract text content using Readability-like approach
            text_content = await asyncio.wait_for(
                browser.eval_js(
                    "document.body ? document.body.innerText.substring(0, 50000) : ''"
                ),
                timeout=10
            )

            # Extract metadata
            meta = await asyncio.wait_for(
                browser.eval_js("""
                    (function() {
                        var meta = {};
                        var desc = document.querySelector('meta[name="description"]');
                        if (desc) meta.description = desc.content;
                        var ogTitle = document.querySelector('meta[property="og:title"]');
                        if (ogTitle) meta.og_title = ogTitle.content;
                        var ogDesc = document.querySelector('meta[property="og:description"]');
                        if (ogDesc) meta.og_description = ogDesc.content;
                        return JSON.stringify(meta);
                    })()
                """),
                timeout=5
            )

            result = {
                "ok": True,
                "url": current_url,
                "title": title,
                "html_len": len(html) if html else 0,
                "text_len": len(text_content) if text_content else 0,
                "text": (text_content or "")[:20000],
                "metadata": json.loads(meta) if meta else {},
            }

            return ctx.cors_json_response(result)

        except asyncio.TimeoutError:
            ctx.record_request(is_error=True, count_request=False)
            return ctx.cors_json_response({"ok": False, "error": f"Extraction timed out ({timeout}s)"}, status=408)
        except Exception as e:
            ctx.record_request(is_error=True, count_request=False)
            return ctx.cors_json_response({"ok": False, "error": str(e)}, status=500)



    return handle_v1_cdp_stealth_extract
