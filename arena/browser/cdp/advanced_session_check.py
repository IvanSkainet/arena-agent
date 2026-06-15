"""CDP advanced session check handler."""
from __future__ import annotations

from urllib.parse import parse_qs

from arena.browser.cdp.advanced_common import get_active_browser
from arena.handler_context import CdpAdvancedHandlerContext


def make_cdp_session_check_handler(ctx: CdpAdvancedHandlerContext):
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


    return handle_v1_cdp_session_check
