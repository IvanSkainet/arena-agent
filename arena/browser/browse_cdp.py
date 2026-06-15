"""CDP backend for the high-level browser browse endpoint."""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from typing import Any

from arena.handler_context import BrowserBrowseHandlerContext


async def ensure_cdp_browse_manager(ctx: BrowserBrowseHandlerContext):
    cdp_state = ctx.cdp_state
    if not cdp_state["connected"]:
        try:
            cdp = ctx.get_cdp_module()
            if cdp:
                mgr = cdp.CDPTabManager(
                    port=cdp_state["port"],
                    headless=cdp_state["headless"],
                    auto_launch=True,
                )
                await asyncio.wait_for(mgr.connect(), timeout=60)
                cdp_state["manager"] = mgr
                cdp_state["connected"] = True
                cdp_state["last_connect_time"] = datetime.now(timezone.utc).isoformat()
                ctx.start_cdp_watcher()
            else:
                ctx.record_request(is_error=True, count_request=False)
                return None, ctx.cors_json_response({"ok": False, "error": "CDP module not available"}, status=503)
        except Exception as e:
            ctx.record_request(is_error=True, count_request=False)
            return None, ctx.cors_json_response({"ok": False, "error": f"CDP auto-connect failed: {e}"}, status=503)

    mgr = cdp_state.get("manager")
    if not mgr or not mgr.active_tab or not mgr.active_tab.connected:
        ctx.record_request(is_error=True, count_request=False)
        return None, ctx.cors_json_response({"ok": False, "error": "No active CDP tab"}, status=503)
    return mgr, None


async def run_cdp_extract(ctx: BrowserBrowseHandlerContext, mgr: Any, *, url: str, wait_for: str | None, timeout: float):
    browser = mgr.active_tab._browser
    await asyncio.wait_for(browser.navigate(url, wait=True), timeout=timeout)
    if wait_for:
        safe_selector = json.dumps(wait_for)
        expr = (
            "new Promise((resolve, reject) => { const check = () => { "
            f"if (document.querySelector({safe_selector})) resolve(true); "
            "else setTimeout(check, 200); }; "
            f"setTimeout(() => reject('timeout'), {(timeout - 2) * 1000}); check(); }})"
        )
        await asyncio.wait_for(browser.eval_js(expr), timeout=timeout)
    text_content = await asyncio.wait_for(
        browser.eval_js("document.body ? document.body.innerText.substring(0, 50000) : ''"),
        timeout=10,
    )
    title = await asyncio.wait_for(browser.eval_js("document.title"), timeout=5)
    return ctx.cors_json_response({
        "ok": True,
        "backend": "cdp",
        "stealth": False,
        "url": url,
        "title": title,
        "text": (text_content or "")[:20000],
        "text_len": len(text_content or ""),
    })


async def run_cdp_shot(ctx: BrowserBrowseHandlerContext, mgr: Any, *, url: str, timeout: float, width: int, height: int):
    browser = mgr.active_tab._browser
    await asyncio.wait_for(
        browser.send(
            "Emulation.setDeviceMetricsOverride",
            {"width": width, "height": height, "deviceScaleFactor": 1, "mobile": False},
        ),
        timeout=5,
    )
    await asyncio.wait_for(browser.navigate(url, wait=True), timeout=timeout)
    res = await asyncio.wait_for(browser.send("Page.captureScreenshot", {"format": "png"}), timeout=15)
    if res and "result" in res and "data" in res["result"]:
        return ctx.cors_json_response({
            "ok": True,
            "backend": "cdp",
            "stealth": False,
            "format": "png",
            "data": res["result"]["data"],
            "width": width,
            "height": height,
        })

    ctx.record_request(is_error=True, count_request=False)
    return ctx.cors_json_response({"ok": False, "error": "Screenshot returned no data"}, status=500)


async def run_cdp_click(ctx: BrowserBrowseHandlerContext, mgr: Any, *, body: dict[str, Any], timeout: float):
    selector = body.get("selector")
    if not selector:
        return ctx.cors_json_response({"ok": False, "error": "missing 'selector' for click action"}, status=400)
    await asyncio.wait_for(mgr.active_tab.click(selector), timeout=timeout)
    return ctx.cors_json_response({"ok": True, "backend": "cdp", "stealth": False, "action": "click", "selector": selector})


async def run_cdp_type(ctx: BrowserBrowseHandlerContext, mgr: Any, *, body: dict[str, Any], timeout: float):
    selector = body.get("selector")
    text = body.get("text")
    if not selector or not text:
        return ctx.cors_json_response({"ok": False, "error": "missing 'selector' and 'text' for type action"}, status=400)
    await asyncio.wait_for(mgr.active_tab.type_text(selector, text), timeout=timeout)
    return ctx.cors_json_response({"ok": True, "backend": "cdp", "stealth": False, "action": "type", "selector": selector})


async def run_cdp_browse(
    ctx: BrowserBrowseHandlerContext,
    *,
    body: dict[str, Any],
    action: str,
    url: str,
    wait_for: str | None,
    timeout: float,
    width: int,
    height: int,
):
    """Execute a /v1/browser/browse request through CDP."""
    mgr, response = await ensure_cdp_browse_manager(ctx)
    if response:
        return response

    try:
        if action == "extract":
            return await run_cdp_extract(ctx, mgr, url=url, wait_for=wait_for, timeout=timeout)
        if action == "shot":
            return await run_cdp_shot(ctx, mgr, url=url, timeout=timeout, width=width, height=height)
        if action == "click":
            return await run_cdp_click(ctx, mgr, body=body, timeout=timeout)
        if action == "type":
            return await run_cdp_type(ctx, mgr, body=body, timeout=timeout)

        ctx.record_request(is_error=True, count_request=False)
        return ctx.cors_json_response({"ok": False, "error": f"Unknown action: {action}. Supported: extract, shot, click, type"}, status=400)
    except asyncio.TimeoutError:
        ctx.record_request(is_error=True, count_request=False)
        return ctx.cors_json_response({"ok": False, "error": f"CDP {action} timed out ({timeout}s)"}, status=408)
    except Exception as e:
        ctx.record_request(is_error=True, count_request=False)
        return ctx.cors_json_response({"ok": False, "error": str(e)}, status=500)
