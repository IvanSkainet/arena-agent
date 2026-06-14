"""CDP network interception handlers."""
from __future__ import annotations

from dataclasses import dataclass

from aiohttp import web

from arena.handler_context import CdpInterceptHandlerContext


@dataclass(frozen=True)
class CdpInterceptHandlers:
    start: object
    stop: object
    rule: object


def make_cdp_intercept_handlers(ctx: CdpInterceptHandlerContext) -> CdpInterceptHandlers:
    async def handle_v1_cdp_intercept_start(request):
        """POST /v1/browser/cdp/intercept/start — Start network interception.
    
        Body JSON (optional):
            patterns: list of Fetch pattern dicts (default: intercept all)
        """
        r = ctx.require_auth(request)
        if r: return r
        ctx.record_request()
    
        if not ctx.cdp_state["connected"]:
            ctx.record_request(is_error=True, count_request=False)
            return ctx.cors_json_response({"ok": False, "error": "CDP not connected"}, status=400)
    
        cdp = ctx.get_cdp_module()
        if not cdp:
            ctx.record_request(is_error=True, count_request=False)
            return ctx.cors_json_response({"ok": False, "error": "cdp_browser module not found"}, status=500)
    
        try:
            tab, _ = await ctx.cdp_active_tab()
            if not tab or not tab._browser:
                ctx.record_request(is_error=True, count_request=False)
                return ctx.cors_json_response({"ok": False, "error": "No active tab"}, status=400)
        
            if ctx.cdp_state.get("interceptor") and ctx.cdp_state["interceptor"].active:
                return ctx.cors_json_response({"ok": True, "message": "Interception already active"})
        
            patterns = None
            try:
                body = await request.json()
                patterns = body.get("patterns")
            except Exception:
                pass
        
            interceptor = cdp.CDPNetworkInterceptor(tab._browser)
            await interceptor.start(patterns=patterns)
            ctx.cdp_state["interceptor"] = interceptor
        
            return ctx.cors_json_response({
                "ok": True,
                "message": "Network interception started",
            })
        except Exception as e:
            ctx.record_request(is_error=True, count_request=False)
            return ctx.cors_json_response({"ok": False, "error": str(e)}, status=500)


    async def handle_v1_cdp_intercept_stop(request):
        """POST /v1/browser/cdp/intercept/stop — Stop network interception."""
        r = ctx.require_auth(request)
        if r: return r
        ctx.record_request()
    
        interceptor = ctx.cdp_state.get("interceptor")
        if not interceptor or not interceptor.active:
            return ctx.cors_json_response({"ok": True, "message": "Interception not active"})
    
        try:
            await interceptor.stop()
            return ctx.cors_json_response({"ok": True, "message": "Interception stopped"})
        except Exception as e:
            ctx.record_request(is_error=True, count_request=False)
            return ctx.cors_json_response({"ok": False, "error": str(e)}, status=500)


    async def handle_v1_cdp_intercept_rule(request):
        """POST /v1/browser/cdp/intercept/rule — Add interception rule.
        DELETE /v1/browser/cdp/intercept/rule — Remove interception rule.
        GET /v1/browser/cdp/intercept/rules — List interception rules.
    
        POST Body JSON:
            name: string (required)
            url_pattern: string (optional)
            resource_type: string (optional)
            action: "block" | "redirect" | "modify_headers" | "mock" (required)
            redirect_url: string (for action="redirect")
            mock_status: int (for action="mock", default: 200)
            mock_body: string (for action="mock")
            mock_content_type: string (for action="mock", default: "text/plain")
    
        DELETE Body JSON:
            name: string (required)
        """
        r = ctx.require_auth(request)
        if r: return r
        ctx.record_request()
    
        cdp = ctx.get_cdp_module()
        if not cdp:
            ctx.record_request(is_error=True, count_request=False)
            return ctx.cors_json_response({"ok": False, "error": "cdp_browser module not found"}, status=500)
    
        interceptor = ctx.cdp_state.get("interceptor")
    
        if request.method == "GET":
            if not interceptor:
                return ctx.cors_json_response({"ok": True, "rules": [], "count": 0})
            rules = interceptor.get_rules()
            return ctx.cors_json_response({
                "ok": True,
                "rules": [rule.to_dict() for rule in rules],
                "count": len(rules),
            })
    
        try:
            body = await request.json()
        except Exception:
            ctx.record_request(is_error=True, count_request=False)
            return ctx.cors_json_response({"ok": False, "error": "Invalid JSON body"}, status=400)
    
        if request.method == "DELETE":
            name = body.get("name")
            if not name:
                ctx.record_request(is_error=True, count_request=False)
                return ctx.cors_json_response({"ok": False, "error": "missing 'name'"}, status=400)
        
            if not interceptor:
                ctx.record_request(is_error=True, count_request=False)
                return ctx.cors_json_response({"ok": False, "error": "No active interceptor"}, status=400)
        
            removed = interceptor.remove_rule(name)
            return ctx.cors_json_response({
                "ok": removed,
                "name": name,
            })
    
        # POST — add rule
        if not interceptor or not interceptor.active:
            ctx.record_request(is_error=True, count_request=False)
            return ctx.cors_json_response({"ok": False, "error": "Interception not active. Start first."}, status=400)
    
        name = body.get("name", "")
        action = body.get("action")
        if not action:
            ctx.record_request(is_error=True, count_request=False)
            return ctx.cors_json_response({"ok": False, "error": "missing 'action'"}, status=400)
    
        try:
            rule = cdp.InterceptRule(
                name=name,
                url_pattern=body.get("url_pattern"),
                resource_type=body.get("resource_type"),
                action=action,
                redirect_url=body.get("redirect_url"),
                mock_status=body.get("mock_status", 200),
                mock_body=body.get("mock_body"),
                mock_content_type=body.get("mock_content_type", "text/plain"),
                modify_request_headers=body.get("modify_request_headers"),
                remove_request_headers=body.get("remove_request_headers"),
            )
            interceptor.add_rule(rule)
        
            return ctx.cors_json_response({
                "ok": True,
                "rule": rule.to_dict(),
            })
        except ValueError as e:
            return ctx.cors_json_response({"ok": False, "error": str(e)}, status=400)
        except Exception as e:
            ctx.record_request(is_error=True, count_request=False)
            return ctx.cors_json_response({"ok": False, "error": str(e)}, status=500)

    return CdpInterceptHandlers(
        start=handle_v1_cdp_intercept_start,
        stop=handle_v1_cdp_intercept_stop,
        rule=handle_v1_cdp_intercept_rule,
    )
