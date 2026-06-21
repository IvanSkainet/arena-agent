"""Desktop automation and control lease route registration."""
from __future__ import annotations

from collections.abc import Callable, Mapping

from aiohttp import web



def register_desktop_routes(app: web.Application, h: Mapping[str, Callable]) -> None:
    app.router.add_get("/v1/desktop/screenshot", h["handle_v1_desktop_screenshot"])
    app.router.add_get("/v1/desktop/displays", h["handle_v1_desktop_displays"])
    app.router.add_post("/v1/desktop/click", h["handle_v1_desktop_click"])
    app.router.add_post("/v1/desktop/type", h["handle_v1_desktop_type"])
    app.router.add_post("/v1/desktop/key", h["handle_v1_desktop_key"])
    app.router.add_post("/v1/desktop/mouse", h["handle_v1_desktop_mouse"])
    app.router.add_get("/v1/desktop/windows", h["handle_v1_desktop_windows"])
    app.router.add_get("/v1/desktop/active_window", h["handle_v1_desktop_active_window"])
    app.router.add_post("/v1/desktop/focus", h["handle_v1_desktop_focus"])
    app.router.add_post("/v1/desktop/window_action", h["handle_v1_desktop_window_action"])
    app.router.add_post("/v1/desktop/resolve_text_target", h["handle_v1_desktop_resolve_text_target"])
    app.router.add_post("/v1/desktop/ocr", h["handle_v1_desktop_ocr"])
    app.router.add_post("/v1/desktop/find_text", h["handle_v1_desktop_find_text"])
    app.router.add_post("/v1/desktop/click_text", h["handle_v1_desktop_click_text"])

    app.router.add_get("/v1/control/status", h["handle_v1_control_status"])
    app.router.add_post("/v1/control/pause", h["handle_v1_control_pause"])
    app.router.add_post("/v1/control/resume", h["handle_v1_control_resume"])
    app.router.add_post("/v1/control/revoke", h["handle_v1_control_revoke"])
