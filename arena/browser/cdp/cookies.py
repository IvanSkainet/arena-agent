"""CDP cookie and cookie-profile handlers."""
from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import parse_qs

from aiohttp import web

from arena.browser.cdp.cookie_manager import ensure_cookie_manager
from arena.handler_context import CdpCookiesHandlerContext


@dataclass(frozen=True)
class CdpCookiesHandlers:
    get: object
    set: object
    delete: object
    clear: object
    profiles: object


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
