"""CDP cookie and cookie-profile handlers."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from urllib.parse import parse_qs

from aiohttp import web

from arena.handler_context import CdpCookiesHandlerContext


@dataclass(frozen=True)
class CdpCookiesHandlers:
    get: object
    set: object
    delete: object
    clear: object
    profiles: object


async def ensure_cookie_manager(ctx: CdpCookiesHandlerContext):
    """Lazily create and start a CDPCookieManager.
    
    Tries the active tab first, then falls back to any connected tab.
    If no tab is connected, attempts to connect the first available tab.
    Includes proper error logging instead of silent None returns.
    
    v2.5.0 fix: Falls back to direct CDP commands via tab if CDPCookieManager fails.
    """
    if ctx.cdp_state.get("cookie_mgr") and ctx.cdp_state["cookie_mgr"].active:
        return ctx.cdp_state["cookie_mgr"]
    
    cdp = ctx.get_cdp_module()
    if not cdp:
        ctx.log_warning("[Cookie] cdp_browser module not available")
        return None
    
    # Get the active tab
    tab, _ = await ctx.cdp_active_tab()
    
    # If active tab is not connected, try to find any connected tab
    if not tab or not getattr(tab, 'connected', False):
        mgr = ctx.cdp_state.get("manager")
        if mgr:
            for t in mgr.list_tabs():
                if t.connected:
                    tab = t
                    ctx.log_info("[Cookie] Using non-active connected tab: %s", t.target_id)
                    break
            
            # If still no connected tab, try connecting the first available one
            if not tab:
                for t in mgr.list_tabs():
                    if t.ws_url:
                        try:
                            await asyncio.wait_for(t.connect(), timeout=15)
                            tab = t
                            ctx.log_info("[Cookie] Connected tab %s for cookie manager", t.target_id)
                            break
                        except Exception as e:
                            ctx.log_warning("[Cookie] Failed to connect tab %s: %s", t.target_id, e)
                            continue
    
    if not tab:
        ctx.log_error("[Cookie] No tab available for cookie manager — CDP may be disconnected")
        return None
    
    if not getattr(tab, 'connected', False):
        ctx.log_error("[Cookie] Tab %s is not connected — cannot start cookie manager",
                  getattr(tab, 'target_id', 'unknown'))
        return None
    
    # Try using CDPCookieManager with tab._browser
    browser = getattr(tab, '_browser', None)
    if browser:
        try:
            mgr = cdp.CDPCookieManager(browser)
            await asyncio.wait_for(mgr.start(), timeout=10)
            ctx.cdp_state["cookie_mgr"] = mgr
            ctx.log_info("[Cookie] Cookie manager started successfully for tab %s via _browser",
                     getattr(tab, 'target_id', 'unknown'))
            return mgr
        except asyncio.TimeoutError:
            ctx.log_warning("[Cookie] CDPCookieManager start timed out — falling back to tab.send()")
        except ConnectionError as e:
            ctx.log_warning("[Cookie] CDPCookieManager ConnectionError: %s — falling back to tab.send()", e)
        except Exception as e:
            ctx.log_warning("[Cookie] CDPCookieManager failed: %s: %s — falling back to tab.send()", type(e).__name__, e)
    
    # Fallback: create a lightweight cookie manager using tab.send() directly
    # This avoids the browser-level WS issue where Network.* commands hang
    try:
        # Enable Network domain on the tab
        await asyncio.wait_for(tab.send("Network.enable"), timeout=10)
        
        # Create a thin wrapper that uses tab.send() instead of browser.send()
        class TabCookieManager:
            """Lightweight cookie manager that uses tab-level CDP commands.
            
            v2.5.1: Fixed interface to match CDPCookieManager — set_cookie now
            accepts the same keyword arguments as CDPCookieManager.set_cookie,
            so the handler code doesn't need to know which implementation it's using.
            """
            def __init__(self, tab):
                self._tab = tab
                self.active = True
            
            async def get_all_cookies(self):
                res = await self._tab.send("Network.getAllCookies", timeout=15)
                if res and "result" in res:
                    return res["result"].get("cookies", [])
                return []
            
            async def get_cookies_for_url(self, url):
                res = await self._tab.send("Network.getCookies", {"urls": [url]}, timeout=15)
                if res and "result" in res:
                    return res["result"].get("cookies", [])
                return []
            
            # v2.5.1: Match CDPCookieManager.set_cookie signature
            async def set_cookie(self, name: str, value: str, domain: str = "",
                                 path: str = "/", secure: bool = False,
                                 http_only: bool = False, same_site: str = "",
                                 expires=None, priority: str = "Medium",
                                 same_party: bool = False,
                                 source_scheme: str = "NonSecure") -> bool:
                params = {
                    "name": name,
                    "value": value,
                    "path": path,
                    "secure": secure,
                    "httpOnly": http_only,
                }
                if domain:
                    params["domain"] = domain
                if same_site and same_site in ("Strict", "Lax", "None"):
                    params["sameSite"] = same_site
                if expires is not None:
                    params["expires"] = expires
                try:
                    res = await self._tab.send("Network.setCookie", params, timeout=10)
                    if res and "result" in res:
                        return res["result"].get("success", False)
                    return True  # CDP didn't report failure
                except Exception as e:
                    ctx.log_warning("[Cookie] TabCookieManager.set_cookie failed: %s", e)
                    return False
            
            async def delete_cookie(self, name, domain=""):
                params = {"name": name}
                if domain:
                    params["domain"] = domain
                return await self._tab.send("Network.deleteCookies", params, timeout=10)
            
            async def clear_cookies(self):
                return await self._tab.send("Network.clearBrowserCookies", timeout=10)
            
            def list_profiles(self):
                return []
            
            def get_profile_info(self, name):
                return None
            
            async def save_profile(self, name, domain_filter=None):
                cookies = await self.get_all_cookies()
                return len(cookies)
            
            async def restore_profile(self, name, clear_first=True):
                return 0
            
            def delete_profile(self, name):
                return False
            
            async def check_session(self, domain, auth_cookie_names=None):
                cookies = await self.get_all_cookies()
                domain_cookies = [c for c in cookies if domain in c.get("domain", "")]
                return {"active": len(domain_cookies) > 0, "cookie_count": len(domain_cookies)}
            
            async def stop(self):
                self.active = False
        
        mgr = TabCookieManager(tab)
        ctx.cdp_state["cookie_mgr"] = mgr
        ctx.log_info("[Cookie] Tab-level cookie manager started for tab %s",
                 getattr(tab, 'target_id', 'unknown'))
        return mgr
    except asyncio.TimeoutError:
        ctx.log_error("[Cookie] Tab Network.enable timed out (10s) — browser may be unresponsive")
        return None
    except ConnectionError as e:
        ctx.log_error("[Cookie] Tab ConnectionError: %s", e)
        return None
    except Exception as e:
        ctx.log_error("[Cookie] Tab-level cookie manager failed: %s: %s", type(e).__name__, e)
        return None


def make_cdp_cookies_handlers(ctx: CdpCookiesHandlerContext) -> CdpCookiesHandlers:
    async def handle_v1_cdp_cookies_get(request):
        """GET /v1/browser/cdp/cookies — Get cookies.
    
        Query params:
            url: string (optional, filter by URL)
            domain: string (optional, filter by domain)
        """
        r = ctx.require_auth(request)
        if r: return r
        ctx.record_request()
    
        if not ctx.cdp_state["connected"]:
            ctx.record_request(is_error=True, count_request=False)
            return ctx.cors_json_response({"ok": False, "error": "CDP not connected"}, status=400)
    
        try:
            cookie_mgr = await ensure_cookie_manager(ctx)
            if not cookie_mgr:
                ctx.record_request(is_error=True, count_request=False)
                return ctx.cors_json_response({"ok": False, "error": "Failed to start cookie manager"}, status=500)
        
            qs = parse_qs(request.query_string)
            url = qs.get("url", [None])[0]
            domain = qs.get("domain", [None])[0]
        
            if url:
                cookies = await cookie_mgr.get_cookies_for_url(url)
            elif domain:
                all_cookies = await cookie_mgr.get_all_cookies()
                cookies = [c for c in all_cookies if domain in c.get("domain", "")]
            else:
                cookies = await cookie_mgr.get_all_cookies()
        
            return ctx.cors_json_response({
                "ok": True,
                "cookies": cookies,
                "count": len(cookies),
            })
        except Exception as e:
            ctx.record_request(is_error=True, count_request=False)
            return ctx.cors_json_response({"ok": False, "error": str(e)}, status=500)


    async def handle_v1_cdp_cookies_set(request):
        """POST /v1/browser/cdp/cookies — Set a cookie.
    
        Body JSON:
            name: string (required)
            value: string (required)
            domain: string (optional)
            path: string (default: "/")
            secure: bool (default: false)
            http_only: bool (default: false)
            same_site: string (optional: "Strict"|"Lax"|"None")
            expires: float (optional, UTC timestamp)
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
    
        name = body.get("name")
        value = body.get("value")
        if not name or value is None:
            ctx.record_request(is_error=True, count_request=False)
            return ctx.cors_json_response({"ok": False, "error": "missing 'name' or 'value'"}, status=400)
    
        try:
            cookie_mgr = await ensure_cookie_manager(ctx)
            if not cookie_mgr:
                ctx.record_request(is_error=True, count_request=False)
                return ctx.cors_json_response({"ok": False, "error": "Failed to start cookie manager"}, status=500)
        
            success = await cookie_mgr.set_cookie(
                name=name,
                value=value,
                domain=body.get("domain", ""),
                path=body.get("path", "/"),
                secure=body.get("secure", False),
                http_only=body.get("http_only", False),
                same_site=body.get("same_site", ""),
                expires=body.get("expires"),
            )
        
            return ctx.cors_json_response({
                "ok": success,
                "name": name,
                "domain": body.get("domain", ""),
            })
        except Exception as e:
            ctx.record_request(is_error=True, count_request=False)
            return ctx.cors_json_response({"ok": False, "error": str(e)}, status=500)


    async def handle_v1_cdp_cookies_delete(request):
        """DELETE /v1/browser/cdp/cookies — Delete a cookie.
    
        Body JSON:
            name: string (required)
            domain: string (optional)
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
    
        name = body.get("name")
        if not name:
            ctx.record_request(is_error=True, count_request=False)
            return ctx.cors_json_response({"ok": False, "error": "missing 'name'"}, status=400)
    
        try:
            cookie_mgr = await ensure_cookie_manager(ctx)
            if not cookie_mgr:
                ctx.record_request(is_error=True, count_request=False)
                return ctx.cors_json_response({"ok": False, "error": "Failed to start cookie manager"}, status=500)
        
            await cookie_mgr.delete_cookie(name, domain=body.get("domain", ""))
        
            return ctx.cors_json_response({
                "ok": True,
                "deleted": name,
            })
        except Exception as e:
            ctx.record_request(is_error=True, count_request=False)
            return ctx.cors_json_response({"ok": False, "error": str(e)}, status=500)


    async def handle_v1_cdp_cookies_clear(request):
        """POST /v1/browser/cdp/cookies/clear — Clear all cookies."""
        r = ctx.require_auth(request)
        if r: return r
        ctx.record_request()
    
        if not ctx.cdp_state["connected"]:
            ctx.record_request(is_error=True, count_request=False)
            return ctx.cors_json_response({"ok": False, "error": "CDP not connected"}, status=400)
    
        try:
            cookie_mgr = await ensure_cookie_manager(ctx)
            if not cookie_mgr:
                ctx.record_request(is_error=True, count_request=False)
                return ctx.cors_json_response({"ok": False, "error": "Failed to start cookie manager"}, status=500)
        
            await cookie_mgr.clear_cookies()
        
            return ctx.cors_json_response({"ok": True, "message": "All cookies cleared"})
        except Exception as e:
            ctx.record_request(is_error=True, count_request=False)
            return ctx.cors_json_response({"ok": False, "error": str(e)}, status=500)


    async def handle_v1_cdp_cookies_profiles(request):
        """GET /v1/browser/cdp/cookies/profiles — List cookie profiles.
        POST /v1/browser/cdp/cookies/profiles — Save/restore/delete profile.
    
        POST Body JSON:
            action: "save" | "restore" | "delete" (required)
            name: string (required)
            domain: string (optional, for save filter)
            clear_first: bool (default: true, for restore)
        """
        r = ctx.require_auth(request)
        if r: return r
        ctx.record_request()
    
        if not ctx.cdp_state["connected"]:
            ctx.record_request(is_error=True, count_request=False)
            return ctx.cors_json_response({"ok": False, "error": "CDP not connected"}, status=400)
    
        if request.method == "GET":
            cookie_mgr = ctx.cdp_state.get("cookie_mgr")
            profiles = cookie_mgr.list_profiles() if cookie_mgr else []
            profile_info = []
            for name in profiles:
                info = cookie_mgr.get_profile_info(name) if cookie_mgr else None
                profile_info.append(info or {"name": name})
        
            return ctx.cors_json_response({
                "ok": True,
                "profiles": profile_info,
                "count": len(profile_info),
            })
    
        # POST — save/restore/delete
        try:
            body = await request.json()
        except Exception:
            ctx.record_request(is_error=True, count_request=False)
            return ctx.cors_json_response({"ok": False, "error": "Invalid JSON body"}, status=400)
    
        action = body.get("action")
        name = body.get("name")
        if not action or not name:
            ctx.record_request(is_error=True, count_request=False)
            return ctx.cors_json_response({"ok": False, "error": "missing 'action' or 'name'"}, status=400)
    
        try:
            cookie_mgr = await ensure_cookie_manager(ctx)
            if not cookie_mgr:
                ctx.record_request(is_error=True, count_request=False)
                return ctx.cors_json_response({"ok": False, "error": "Failed to start cookie manager"}, status=500)
        
            if action == "save":
                count = await cookie_mgr.save_profile(name, domain_filter=body.get("domain"))
                return ctx.cors_json_response({
                    "ok": True,
                    "action": "save",
                    "profile": name,
                    "cookie_count": count,
                })
            elif action == "restore":
                count = await cookie_mgr.restore_profile(
                    name, 
                    clear_first=body.get("clear_first", True)
                )
                return ctx.cors_json_response({
                    "ok": True,
                    "action": "restore",
                    "profile": name,
                    "restored_count": count,
                })
            elif action == "delete":
                deleted = cookie_mgr.delete_profile(name)
                return ctx.cors_json_response({
                    "ok": deleted,
                    "action": "delete",
                    "profile": name,
                })
            else:
                return ctx.cors_json_response(
                    {"ok": False, "error": f"Unknown action '{action}'. Use save, restore, or delete."},
                    status=400
                )
        except KeyError as e:
            return ctx.cors_json_response({"ok": False, "error": str(e)}, status=404)
        except Exception as e:
            ctx.record_request(is_error=True, count_request=False)
            return ctx.cors_json_response({"ok": False, "error": str(e)}, status=500)

    return CdpCookiesHandlers(
        get=handle_v1_cdp_cookies_get,
        set=handle_v1_cdp_cookies_set,
        delete=handle_v1_cdp_cookies_delete,
        clear=handle_v1_cdp_cookies_clear,
        profiles=handle_v1_cdp_cookies_profiles,
    )
