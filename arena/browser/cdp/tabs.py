"""CDP tab management handlers."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass

from aiohttp import web

from arena.handler_context import CdpTabsHandlerContext


@dataclass(frozen=True)
class CdpTabsHandlers:
    tabs: object
    new: object
    close: object
    activate: object


def make_cdp_tabs_handlers(ctx: CdpTabsHandlerContext) -> CdpTabsHandlers:
    async def handle_v1_cdp_tabs(request):
        """GET /v1/browser/cdp/tabs — List all tracked tabs.
    
        Auto-connects any disconnected tabs that have ws_url before listing.
        """
        r = ctx.require_auth(request)
        if r: return r
        ctx.record_request()
    
        if not ctx.cdp_state["connected"] or not ctx.cdp_state["manager"]:
            return ctx.cors_json_response({"ok": True, "tabs": [], "tab_count": 0})
    
        mgr = ctx.cdp_state["manager"]
        tabs = mgr.list_tabs()
    
        # Auto-connect disconnected tabs that have ws_url (lazy connect)
        for tab in tabs:
            if not tab.connected and tab.ws_url:
                try:
                    await asyncio.wait_for(tab.connect(), timeout=15)
                    ctx.log_debug("[CDP-Tabs] Auto-connected tab %s", tab.target_id)
                except Exception as e:
                    ctx.log_debug("[CDP-Tabs] Auto-connect failed for %s: %s", tab.target_id, e)
    
        return ctx.cors_json_response({
            "ok": True,
            "tabs": [tab.to_dict() for tab in tabs],
            "tab_count": len(tabs),
            "active_tab_id": mgr.active_tab_id,
        })


    async def handle_v1_cdp_tabs_new(request):
        """POST /v1/browser/cdp/tabs/new — Open new tab.
    
        Body JSON:
            url: string (default: "about:blank")
            activate: bool (default: true)
        """
        r = ctx.require_auth(request)
        if r: return r
        ctx.record_request()
    
        if not ctx.cdp_state["connected"] or not ctx.cdp_state["manager"]:
            ctx.record_request(is_error=True, count_request=False)
            return ctx.cors_json_response({"ok": False, "error": "CDP not connected"}, status=400)
    
        url = "about:blank"
        activate = True
        try:
            body = await request.json()
            url = body.get("url", "about:blank")
            activate = body.get("activate", True)
        except Exception:
            pass
    
        mgr = ctx.cdp_state["manager"]
    
        try:
            tab = await mgr.new_tab(url, activate=activate)
            return ctx.cors_json_response({
                "ok": True,
                "tab": tab.to_dict(),
                "tab_id": tab.target_id,
            })
        except Exception as e:
            ctx.record_request(is_error=True, count_request=False)
            return ctx.cors_json_response({"ok": False, "error": str(e)}, status=500)


    async def handle_v1_cdp_tabs_close(request):
        """POST /v1/browser/cdp/tabs/close — Close a tab.
    
        Body JSON:
            tab_id: string (required)
        """
        r = ctx.require_auth(request)
        if r: return r
        ctx.record_request()
    
        if not ctx.cdp_state["connected"] or not ctx.cdp_state["manager"]:
            ctx.record_request(is_error=True, count_request=False)
            return ctx.cors_json_response({"ok": False, "error": "CDP not connected"}, status=400)
    
        try:
            body = await request.json()
        except Exception:
            ctx.record_request(is_error=True, count_request=False)
            return ctx.cors_json_response({"ok": False, "error": "Invalid JSON body"}, status=400)
    
        tab_id = body.get("tab_id")
        if not tab_id:
            ctx.record_request(is_error=True, count_request=False)
            return ctx.cors_json_response({"ok": False, "error": "missing 'tab_id'"}, status=400)
    
        mgr = ctx.cdp_state["manager"]
    
        try:
            success = await mgr.close_tab(tab_id)
            return ctx.cors_json_response({
                "ok": success,
                "tab_id": tab_id,
                "remaining_tabs": mgr.tab_count,
            })
        except Exception as e:
            ctx.record_request(is_error=True, count_request=False)
            return ctx.cors_json_response({"ok": False, "error": str(e)}, status=500)


    async def handle_v1_cdp_tabs_activate(request):
        """POST /v1/browser/cdp/tabs/activate — Activate a tab.
    
        Body JSON:
            tab_id: string (required)
        """
        r = ctx.require_auth(request)
        if r: return r
        ctx.record_request()
    
        if not ctx.cdp_state["connected"] or not ctx.cdp_state["manager"]:
            ctx.record_request(is_error=True, count_request=False)
            return ctx.cors_json_response({"ok": False, "error": "CDP not connected"}, status=400)
    
        try:
            body = await request.json()
        except Exception:
            ctx.record_request(is_error=True, count_request=False)
            return ctx.cors_json_response({"ok": False, "error": "Invalid JSON body"}, status=400)
    
        tab_id = body.get("tab_id")
        if not tab_id:
            ctx.record_request(is_error=True, count_request=False)
            return ctx.cors_json_response({"ok": False, "error": "missing 'tab_id'"}, status=400)
    
        mgr = ctx.cdp_state["manager"]
    
        success = mgr.activate(tab_id)
        return ctx.cors_json_response({
            "ok": success,
            "tab_id": tab_id,
            "active_tab_id": mgr.active_tab_id,
        })

    return CdpTabsHandlers(
        tabs=handle_v1_cdp_tabs,
        new=handle_v1_cdp_tabs_new,
        close=handle_v1_cdp_tabs_close,
        activate=handle_v1_cdp_tabs_activate,
    )
