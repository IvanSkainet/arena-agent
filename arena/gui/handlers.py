"""Handlers and templates for the built-in dashboard GUI."""
from __future__ import annotations

import hmac
import socket
from dataclasses import dataclass
from pathlib import Path

from aiohttp import web

from arena.handler_context import GuiHandlerContext

from arena.gui.templates import DASHBOARD_V2_HTML, GUI_LOGIN_HTML
@dataclass(frozen=True)
class GuiHandlers:
    gui: object
    gui_v2: object


def make_gui_handlers(ctx: GuiHandlerContext) -> GuiHandlers:
    async def handle_gui_v2(request: web.Request) -> web.Response:
        """GET /gui/v2 — Live dashboard with WebSocket real-time updates.
        Shows login page if no valid URL token.
        """
        cfg = request.app["cfg"]
        url_token = request.query.get("token", "")
        valid_token = bool(url_token) and hmac.compare_digest(url_token, cfg["token"])
        if not valid_token:
            return web.Response(text=GUI_LOGIN_HTML, content_type="text/html", charset="utf-8")
        return web.Response(text=DASHBOARD_V2_HTML, content_type="text/html", charset="utf-8")

    async def handle_gui(request: web.Request) -> web.Response:
        """GET /gui — Dashboard. Shows login page if no valid URL token, then serves dashboard."""
        cfg = request.app["cfg"]
        # Only URL token param is accepted — timing-attack safe.
        url_token = request.query.get("token", "")
        valid_token = bool(url_token) and hmac.compare_digest(url_token, cfg["token"])

        # No valid URL token — show login page.
        # (We require the token in the URL because the dashboard HTML needs it for API calls.)
        if not valid_token:
            return web.Response(text=GUI_LOGIN_HTML, content_type="text/html", charset="utf-8")
        try:
            # Try multiple locations for the dashboard.
            candidates = [
                Path(ctx.bridge_dir) / "dashboard" / "index.html",
                Path(ctx.bridge_dir) / "index.html",
            ]
            for html_path in candidates:
                if html_path.exists():
                    html = html_path.read_text(encoding="utf-8")
                    # Embed ONLY the URL token — never fall back to cfg["token"].
                    html = html.replace("{{TOKEN}}", url_token)
                    html = html.replace("{{VERSION}}", ctx.version)
                    html = html.replace("{{HOST}}", socket.gethostname())
                    return web.Response(text=html, content_type="text/html", charset="utf-8",
                                        headers={"Access-Control-Allow-Origin": "*"})
            # Fallback: minimal dashboard (no token leak).
            fallback = f"""<!DOCTYPE html><html><head><title>Arena Bridge v{ctx.version}</title></head>
            <body style='font-family:monospace;background:#1a1a2e;color:#e0e0e0;padding:2rem'>
            <h1>Arena Unified Bridge v{ctx.version}</h1><p>Dashboard not found.</p>
            <p>API: <a href='/'>/</a> | Health: <a href='/health'>/health</a></p>
            </body></html>"""
            return web.Response(text=fallback, content_type="text/html", charset="utf-8",
                                headers={"Access-Control-Allow-Origin": "*"})
        except Exception:
            return ctx.cors_json_response({"ok": False, "error": "Internal server error"}, status=500)

    return GuiHandlers(gui=handle_gui, gui_v2=handle_gui_v2)
