"""CDP page action handlers."""
from __future__ import annotations

import asyncio
import base64 as _b64
import time
from dataclasses import dataclass
from urllib.parse import parse_qs

from aiohttp import web

from arena.handler_context import CdpPageHandlerContext


@dataclass(frozen=True)
class CdpPageHandlers:
    navigate: object
    screenshot: object
    dom: object
    eval: object
    click: object
    type: object


def make_cdp_page_handlers(ctx: CdpPageHandlerContext) -> CdpPageHandlers:
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
        r = ctx.require_auth(request)
        if r: return r
        ctx.record_request()

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


    async def handle_v1_cdp_eval(request):
        """POST /v1/browser/cdp/eval — Evaluate JavaScript.

        Body JSON:
            expression: string (required)
            tab_id: string (optional)
            timeout: number (optional, default: 14) — CDP-level timeout in seconds (max 60)

        v2.3.0: Added 15s hard timeout to prevent system freezes from
        infinite JS loops or huge DOM serialization. Results >1MB are
        truncated to prevent OOM.
        v2.5.1: Configurable timeout, better error messages for heavy eval,
                and explicit `ok: false` with reason when JS throws.
        """
        r = ctx.require_auth(request)
        if r: return r
        ctx.record_request()

        try:
            body = await request.json()
        except Exception:
            ctx.record_request(is_error=True, count_request=False)
            return ctx.cors_json_response({"ok": False, "error": "Invalid JSON body"}, status=400)

        expression = body.get("expression")
        if not expression:
            ctx.record_request(is_error=True, count_request=False)
            return ctx.cors_json_response({"ok": False, "error": "missing 'expression' parameter"}, status=400)

        # v2.5.1: Allow caller to specify a longer timeout for heavy computations
        cdp_timeout = min(body.get("timeout", 14), 60)  # Cap at 60s
        asyncio_timeout = cdp_timeout + 1

        tab_id = body.get("tab_id")
        tab, err = await ctx.cdp_active_tab(tab_id)
        if err: return err

        try:
            # v2.5.1: Use CDP Runtime.evaluate directly so we can distinguish
            # between JS exceptions and transport-level failures.
            eval_result = await asyncio.wait_for(
                tab.send("Runtime.evaluate", {
                    "expression": expression,
                    "returnByValue": True,
                    "timeout": cdp_timeout * 1000,  # CDP expects ms
                }),
                timeout=asyncio_timeout
            )

            if eval_result and "result" in eval_result:
                inner = eval_result["result"]
                # Check for JS exception
                if "exceptionDetails" in inner:
                    exc = inner["exceptionDetails"]
                    exc_text = ""
                    if "exception" in exc and "description" in exc["exception"]:
                        exc_text = exc["exception"]["description"]
                    elif "text" in exc:
                        exc_text = exc["text"]
                    ctx.log_warning("[CDP] eval JS exception: %s", exc_text)
                    return ctx.cors_json_response({
                        "ok": False,
                        "error": f"JavaScript exception: {exc_text}",
                        "exception_details": exc,
                    }, status=400)

                # Successful evaluation
                result_val = inner.get("result", {}).get("value")
                # Convert to string for consistency with eval_js behavior
                if result_val is not None:
                    result_str = str(result_val) if not isinstance(result_val, str) else result_val
                else:
                    result_str = None

                # v2.3.0: Truncate large results to prevent OOM / response bloat
                CDP_EVAL_MAX_RESULT = 1 * 1024 * 1024  # 1MB
                truncated = False
                if isinstance(result_str, str) and len(result_str) > CDP_EVAL_MAX_RESULT:
                    original_len = len(result_str)
                    result_str = result_str[:CDP_EVAL_MAX_RESULT] + f"\n...[truncated, {original_len} total chars]"
                    truncated = True
                    ctx.log_warning("[CDP] eval result truncated: %d -> %d chars", original_len, CDP_EVAL_MAX_RESULT)

                return ctx.cors_json_response({
                    "ok": True,
                    "result": result_str,
                    "truncated": truncated,
                    "tab_id": tab.target_id,
                })

            # v2.5.1: CDP returned no result — likely WebSocket issue
            ctx.log_warning("[CDP] eval returned no result — possible WS issue")
            return ctx.cors_json_response({
                "ok": False,
                "error": "CDP returned empty result — WebSocket may be stale. Try reconnecting.",
            }, status=502)

        except asyncio.TimeoutError:
            ctx.record_request(is_error=True, count_request=False)
            ctx.log_error("[CDP] eval_js timed out (%ds) — expression: %.200s", asyncio_timeout, expression)
            return ctx.cors_json_response(
                {"ok": False, "error": f"JavaScript evaluation timed out ({cdp_timeout}s limit). "
                 "The expression may contain an infinite loop or heavy computation. "
                 "Try a shorter expression or increase the 'timeout' parameter.",
                 "timeout": cdp_timeout},
                status=408
            )
        except ConnectionError as e:
            ctx.record_request(is_error=True, count_request=False)
            ctx.log_error("[CDP] eval connection error: %s", e)
            return ctx.cors_json_response(
                {"ok": False, "error": f"CDP connection lost during eval: {e}. Try reconnecting."},
                status=502
            )
        except Exception as e:
            ctx.record_request(is_error=True, count_request=False)
            return ctx.cors_json_response({"ok": False, "error": str(e)}, status=500)


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

    return CdpPageHandlers(
        navigate=handle_v1_cdp_navigate,
        screenshot=handle_v1_cdp_screenshot,
        dom=handle_v1_cdp_dom,
        eval=handle_v1_cdp_eval,
        click=handle_v1_cdp_click,
        type=handle_v1_cdp_type,
    )
