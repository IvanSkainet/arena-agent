"""CDP cookie manager bootstrap/fallback helpers."""
from __future__ import annotations

import asyncio

from arena.handler_context import CdpCookiesHandlerContext


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

