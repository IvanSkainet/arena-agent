"""CDP network monitoring handlers."""
from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import parse_qs

from aiohttp import web

from arena.handler_context import CdpNetworkHandlerContext
from arena.handler_helpers import authed, err_json


@dataclass(frozen=True)
class CdpNetworkHandlers:
    start: object
    stop: object
    requests: object
    har: object


def make_cdp_network_handlers(ctx: CdpNetworkHandlerContext) -> CdpNetworkHandlers:
    @authed(ctx)
    async def handle_v1_cdp_network_start(request):
        """POST /v1/browser/cdp/network/start — Start network monitoring."""
    
        if not ctx.cdp_state["connected"]:
            ctx.record_request(is_error=True, count_request=False)
            return ctx.cors_json_response({"ok": False, "error": "CDP not connected"}, status=400)
    
        cdp = ctx.get_cdp_module()
        if not cdp:
            ctx.record_request(is_error=True, count_request=False)
            return ctx.cors_json_response({"ok": False, "error": "cdp_browser module not found"}, status=500)
    
        try:
            # Get browser from active tab
            tab, _ = await ctx.cdp_active_tab()
            if not tab or not tab._browser:
                ctx.record_request(is_error=True, count_request=False)
                return ctx.cors_json_response({"ok": False, "error": "No active tab with CDP connection"}, status=400)
        
            if ctx.cdp_state.get("monitor") and ctx.cdp_state["monitor"].active:
                return ctx.cors_json_response({"ok": True, "message": "Network monitoring already active"})
        
            max_entries = 1000
            try:
                body = await request.json()
                max_entries = body.get("max_entries", 1000)
            except Exception:
                pass
        
            monitor = cdp.CDPNetworkMonitor(tab._browser, max_entries=max_entries)
            await monitor.start()
            ctx.cdp_state["monitor"] = monitor
        
            return ctx.cors_json_response({
                "ok": True,
                "message": "Network monitoring started",
                "max_entries": max_entries,
            })
        except Exception as e:
            ctx.record_request(is_error=True, count_request=False)
            return ctx.cors_json_response({"ok": False, "error": str(e)}, status=500)


    @authed(ctx)
    async def handle_v1_cdp_network_stop(request):
        """POST /v1/browser/cdp/network/stop — Stop network monitoring."""
    
        monitor = ctx.cdp_state.get("monitor")
        if not monitor or not monitor.active:
            return ctx.cors_json_response({"ok": True, "message": "Network monitoring not active"})
    
        await monitor.stop()
        return ctx.cors_json_response({"ok": True, "message": "Network monitoring stopped"})


    @authed(ctx)
    async def handle_v1_cdp_network_requests(request):
        """GET /v1/browser/cdp/network/requests — Get captured network requests.
    
        Query params:
            url_filter: string (optional)
            resource_type: string (optional)
            include_active: bool (default: true)
        """
    
        monitor = ctx.cdp_state.get("monitor")
        if not monitor:
            return ctx.cors_json_response({"ok": True, "requests": [], "count": 0, "active_count": 0})
    
        qs = parse_qs(request.query_string)
        url_filter = qs.get("url_filter", [None])[0]
        resource_type = qs.get("resource_type", [None])[0]
        include_active = qs.get("include_active", ["true"])[0].lower() == "true"
    
        try:
            finished = monitor.get_requests(url_filter=url_filter, resource_type=resource_type)
            requests_list = [req.to_dict() for req in finished]
        
            result = {
                "ok": True,
                "requests": requests_list,
                "total_finished": monitor.total_requests,
                "active_count": monitor.active_count,
            }
        
            if include_active:
                active = monitor.get_active_requests()
                result["active"] = [req.to_dict() for req in active]
        
            return ctx.cors_json_response(result)
        except Exception as e:
            ctx.record_request(is_error=True, count_request=False)
            return ctx.cors_json_response({"ok": False, "error": str(e)}, status=500)


    @authed(ctx)
    async def handle_v1_cdp_network_har(request):
        """GET /v1/browser/cdp/network/har — Export captured requests as HAR."""
    
        monitor = ctx.cdp_state.get("monitor")
        if not monitor:
            return ctx.cors_json_response({"log": {"version": "1.2", "creator": {"name": "arena-cdp", "version": "1.0"}, "entries": []}})
    
        har = monitor.export_har()
        return ctx.cors_json_response(har)

    return CdpNetworkHandlers(
        start=handle_v1_cdp_network_start,
        stop=handle_v1_cdp_network_stop,
        requests=handle_v1_cdp_network_requests,
        har=handle_v1_cdp_network_har,
    )
