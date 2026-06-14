"""Advanced CDP handlers: session check, stealth helpers, and health dashboard."""
from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from urllib.parse import parse_qs

from aiohttp import web

from arena.handler_context import CdpAdvancedHandlerContext


@dataclass(frozen=True)
class CdpAdvancedHandlers:
    session_check: object
    stealth_extract: object
    stealth_shot: object
    health: object


async def get_active_browser(ctx: CdpAdvancedHandlerContext):
    """Get the active tab's CDPBrowser instance, or None."""
    mgr = ctx.cdp_state.get("manager")
    if not mgr or not ctx.cdp_state["connected"]:
        return None
    tab = mgr.active_tab
    if not tab or not tab.connected:
        return None
    return tab._browser


def make_cdp_advanced_handlers(ctx: CdpAdvancedHandlerContext) -> CdpAdvancedHandlers:
    async def handle_v1_cdp_session_check(request):
        """GET /v1/browser/cdp/session/check — Check session health.
    
        Query params:
            domain: string (required)
            auth_cookie_names: string (comma-separated, optional)
        """
        r = ctx.require_auth(request)
        if r: return r
        ctx.record_request()
    
        if not ctx.cdp_state["connected"]:
            return ctx.cors_json_response({
                "ok": False,
                "connected": False,
                "error": "CDP not connected",
                "detail": "Start or connect a CDP browser session with POST /v1/browser/cdp/connect before checking cookies/session state.",
                "status_endpoint": "/v1/browser/cdp/status",
                "connect_endpoint": "/v1/browser/cdp/connect",
            })
    
        qs = parse_qs(request.query_string)
        domain = qs.get("domain", [None])[0]
        if not domain:
            ctx.record_request(is_error=True, count_request=False)
            return ctx.cors_json_response({"ok": False, "error": "missing 'domain' parameter"}, status=400)
    
        auth_names_str = qs.get("auth_cookie_names", [None])[0]
        auth_cookie_names = auth_names_str.split(",") if auth_names_str else None
    
        try:
            cookie_mgr = await ctx.ensure_cookie_manager()
            if not cookie_mgr:
                ctx.record_request(is_error=True, count_request=False)
                return ctx.cors_json_response({"ok": False, "error": "Failed to start cookie manager"}, status=500)
        
            result = await cookie_mgr.check_session(domain, auth_cookie_names)
            return ctx.cors_json_response({"ok": True, **result})
        except Exception as e:
            ctx.record_request(is_error=True, count_request=False)
            return ctx.cors_json_response({"ok": False, "error": str(e)}, status=500)


    # ---- CDP Stealth Extract/Shot (BrowserAct + CDP integration) ----

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


    async def handle_v1_cdp_health(request):
        """GET /v1/browser/cdp/health — CDP connection health dashboard.

        Returns comprehensive health info including:
        - Connection status and uptime
        - Browser process status
        - WebSocket health
        - Reconnect history
        - Active tab info
        - Memory/resource usage
        """
        r = ctx.require_auth(request)
        if r: return r
        ctx.record_request()

        mgr = ctx.cdp_state.get("manager")
        connected = ctx.cdp_state["connected"]

        health = {
            "ok": True,
            "connected": connected,
            "port": ctx.cdp_state["port"],
            "headless": ctx.cdp_state["headless"],
            "watcher_active": ctx.watcher_active(),
            "reconnect_count": ctx.cdp_state.get("reconnect_count", 0),
            "last_connect_time": ctx.cdp_state.get("last_connect_time"),
            "last_disconnect_reason": ctx.cdp_state.get("last_disconnect_reason"),
            "bridge_uptime_s": round(time.time() - ctx.bridge_start_time),
        }

        if connected and mgr:
            # Browser process info
            if mgr._browser_proc:
                proc = mgr._browser_proc
                health["browser"] = {
                    "pid": proc.pid,
                    "alive": proc.poll() is None,
                    "returncode": proc.returncode,
                }
            else:
                health["browser"] = {"alive": False, "note": "External browser (not launched by bridge)"}

            # Tab info
            tabs = mgr.list_tabs()
            health["tabs"] = {
                "count": len(tabs),
                "active_id": mgr.active_tab_id,
                "details": [t.to_dict() for t in tabs[:10]],
            }

            # Active tab health probe
            if mgr.active_tab and mgr.active_tab.connected:
                health["active_tab"] = {
                    "connected": True,
                    "target_id": mgr.active_tab.target_id,
                    "url": mgr.active_tab.url,
                    "title": mgr.active_tab.title,
                }
                # Quick health check — can we evaluate JS?
                try:
                    result = await asyncio.wait_for(mgr.active_tab.eval_js("1+1"), timeout=3)
                    health["active_tab"]["health_probe"] = "ok" if result == 2 else f"unexpected result: {result}"
                except asyncio.TimeoutError:
                    health["active_tab"]["health_probe"] = "timeout"
                except ConnectionError:
                    health["active_tab"]["health_probe"] = "disconnected"
                except Exception as e:
                    health["active_tab"]["health_probe"] = f"error: {type(e).__name__}"
            else:
                health["active_tab"] = {"connected": False}

            # Connection uptime
            if ctx.cdp_state.get("last_connect_time"):
                try:
                    last = datetime.fromisoformat(ctx.cdp_state["last_connect_time"])
                    uptime = (datetime.now(timezone.utc) - last).total_seconds()
                    health["connection_uptime_s"] = round(uptime)
                except Exception:
                    pass

        else:
            health["browser"] = {"alive": False}
            health["tabs"] = {"count": 0}
            health["active_tab"] = {"connected": False}

        # System resource usage
        try:
            import resource as _resource
            usage = _resource.getrusage(_resource.RUSAGE_SELF)
            health["resources"] = {
                "max_rss_mb": round(usage.ru_maxrss / 1024, 1),
                "user_cpu_s": round(usage.ru_utime, 1),
                "sys_cpu_s": round(usage.ru_stime, 1),
            }
        except Exception:
            pass

        return ctx.cors_json_response(health)

    return CdpAdvancedHandlers(
        session_check=handle_v1_cdp_session_check,
        stealth_extract=handle_v1_cdp_stealth_extract,
        stealth_shot=handle_v1_cdp_stealth_shot,
        health=handle_v1_cdp_health,
    )
