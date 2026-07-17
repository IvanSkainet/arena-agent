"""Handlers and templates for the built-in dashboard GUI."""
from __future__ import annotations

import hmac
import socket
from dataclasses import dataclass
from pathlib import Path

from aiohttp import web
from arena.app_keys import APP_CFG

from arena.handler_context import GuiHandlerContext

from arena.gui.templates import DASHBOARD_V2_HTML, GUI_LOGIN_HTML
@dataclass(frozen=True)
class GuiHandlers:
    gui: object
    gui_v2: object
    gui_asset: object
    gui_asset_manifest: object
    gui_docs: object


def make_gui_handlers(ctx: GuiHandlerContext) -> GuiHandlers:
    async def handle_gui_v2(request: web.Request) -> web.Response:
        """GET /gui/v2 — Live dashboard with WebSocket real-time updates.
        Shows login page if no valid URL token.
        """
        cfg = request.app[APP_CFG]
        url_token = request.query.get("token", "")
        # nosemgrep: nan-injection -- bool() on a string tests non-emptiness; NaN/Inf are float-only concerns and cannot come from a string here.
        valid_token = bool(url_token) and hmac.compare_digest(url_token, cfg["token"])
        if not valid_token:
            return web.Response(text=GUI_LOGIN_HTML, content_type="text/html", charset="utf-8")
        return web.Response(text=DASHBOARD_V2_HTML, content_type="text/html", charset="utf-8")


    async def handle_gui_asset_manifest(request: web.Request) -> web.Response:
        """GET /gui/assets/manifest.json — auto-generated list of every
        boot-loaded JS + body HTML asset. The dashboard shell fetches
        this instead of hardcoding the file lists (v3.91.0).
        """
        from arena.gui.asset_manifest import build_manifest
        try:
            manifest = build_manifest(ctx.bridge_dir)
            return ctx.cors_json_response(manifest)
        except Exception as e:  # noqa: BLE001
            return ctx.cors_json_response(
                {"ok": False, "error": f"{type(e).__name__}: {e}"},
                status=500,
            )

    async def handle_gui_asset(request: web.Request) -> web.Response:
        """GET /gui/assets/{path} — static dashboard assets."""
        rel = request.match_info.get("path", "")
        asset_root = (Path(ctx.bridge_dir) / "dashboard" / "assets").resolve()
        asset_path = (asset_root / rel).resolve()
        try:
            asset_path.relative_to(asset_root)
        except ValueError:
            return web.Response(status=404, text="not found")
        if not asset_path.is_file():
            return web.Response(status=404, text="not found")
        suffix = asset_path.suffix.lower()
        content_type = {
            ".js": "application/javascript",
            ".css": "text/css",
            ".html": "text/html",
            ".svg": "image/svg+xml",
            ".png": "image/png",
        }.get(suffix, "application/octet-stream")
        # v4.48.8: assets are served via URLs cache-busted with
        # ?v={{VERSION}} (see dashboard/index.html). Every version
        # bump forces a fresh URL, so browsers may safely cache the
        # response for the whole session. Cache-Control:no-store was
        # forcing Chromium to re-download all 58 JS + 22 body HTML
        # fragments on every reload -- combined with the per-IP rate
        # limiter (300 req/60 s) this produced HTTP 429s ("Failed
        # to load /gui/assets/00-core.js -- rate limit exceeded")
        # after 3-4 reloads. `immutable` keeps the browser from
        # re-validating; ?v= parameter still guarantees a real
        # upgrade breaks the cache.
        cache_ctrl = "public, max-age=3600, immutable"
        return web.FileResponse(
            asset_path,
            headers={
                "Access-Control-Allow-Origin": "*",
                "Cache-Control": cache_ctrl,
            },
        )

    async def handle_gui_docs(request: web.Request) -> web.Response:
        """GET /gui/docs/{path} — expose the repo's docs/ directory
        so Dashboard links like ``docs/MULTIAGENT.md`` actually
        resolve. Read-only, path-traversal guarded.

        v3.86.4: Markdown files are rendered server-side to HTML with
        the Dashboard's dark theme instead of returned as raw text
        (which browsers show as an unreadable monospace wall). Other
        file types (txt, html, svg, png) pass through untouched.
        """
        rel = request.match_info.get("path", "")
        docs_root = (Path(ctx.bridge_dir) / "docs").resolve()
        docs_path = (docs_root / rel).resolve()
        try:
            docs_path.relative_to(docs_root)
        except ValueError:
            return web.Response(status=404, text="not found")
        if not docs_path.is_file():
            return web.Response(status=404, text="not found")
        suffix = docs_path.suffix.lower()
        if suffix == ".md":
            # Render Markdown -> HTML with the dashboard's dark theme.
            try:
                from arena.gui.markdown_render import render, wrap_page
                raw = docs_path.read_text(encoding="utf-8", errors="replace")
                body = render(raw)
                html_page = wrap_page(docs_path.name, body)
                return web.Response(
                    text=html_page,
                    content_type="text/html",
                    charset="utf-8",
                    headers={
                        "Access-Control-Allow-Origin": "*",
                        "Cache-Control": "no-store",
                    },
                )
            except Exception:
                # Fall back to raw so a rendering bug can't 500 the
                # docs endpoint entirely.
                pass
        content_type = {
            ".md":   "text/markdown; charset=utf-8",
            ".txt":  "text/plain; charset=utf-8",
            ".html": "text/html; charset=utf-8",
            ".svg":  "image/svg+xml",
            ".png":  "image/png",
        }.get(suffix, "application/octet-stream")
        return web.FileResponse(
            docs_path,
            headers={
                "Access-Control-Allow-Origin": "*",
                "Cache-Control": "no-store",
                "Content-Type": content_type,
            },
        )

    async def handle_gui(request: web.Request) -> web.Response:
        """GET /gui — Dashboard. Shows login page if no valid URL token, then serves dashboard."""
        cfg = request.app[APP_CFG]
        # Only URL token param is accepted — timing-attack safe.
        url_token = request.query.get("token", "")
        # nosemgrep: nan-injection -- bool() on a string tests non-emptiness; NaN/Inf are float-only concerns and cannot come from a string here.
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
                    # v3.85.2: force-refresh the HTML on every request so
                    # the version bumper in the asset URLs (?v={{VERSION}})
                    # actually reaches the browser after a bridge upgrade.
                    # Without this the browser cached the old HTML from
                    # v3.85.0 and kept loading `?v=3.85.0` scripts even
                    # after the bridge had already served v3.85.1.
                    return web.Response(text=html, content_type="text/html", charset="utf-8",
                                        headers={
                                            "Access-Control-Allow-Origin": "*",
                                            "Cache-Control": "no-store, no-cache, must-revalidate",
                                            "Pragma": "no-cache",
                                            "Expires": "0",
                                        })
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

    return GuiHandlers(
        gui=handle_gui,
        gui_v2=handle_gui_v2,
        gui_asset=handle_gui_asset,
        gui_asset_manifest=handle_gui_asset_manifest,
        gui_docs=handle_gui_docs,
    )
