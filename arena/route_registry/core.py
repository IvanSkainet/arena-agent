"""Core/public, v1 base, service/admin and browser-fetch route registration."""
from __future__ import annotations

from collections.abc import Callable, Mapping

from aiohttp import web


def register_core_routes(app: web.Application, h: Mapping[str, Callable]) -> None:
    # ---- Public endpoints ----
    app.router.add_get("/", h["handle_index"])
    app.router.add_get("/health", h["handle_health"])
    app.router.add_get("/v1/version", h["handle_v1_version"])

    # ---- v1 API (auth required) ----
    app.router.add_get("/v1/info", h["handle_v1_info"])
    app.router.add_get("/v1/status", h["handle_v1_status"])
    app.router.add_get("/v1/sysinfo", h["handle_v1_sysinfo"])
    app.router.add_get("/v1/capabilities", h["handle_v1_capabilities"])
    app.router.add_get("/v1/hardware", h["handle_v1_hardware"])
    app.router.add_get("/v1/hwinfo", h["handle_v1_hwinfo"])
    app.router.add_get("/v1/inventory", h["handle_v1_inventory"])
    app.router.add_get("/v1/ps", h["handle_v1_ps"])
    app.router.add_get("/v1/audit", h["handle_v1_audit"])
    app.router.add_post("/v1/exec", h["handle_v1_exec"])
    app.router.add_post("/v1/kill", h["handle_v1_kill"])
    app.router.add_post("/v1/upload", h["handle_v1_upload"])
    app.router.add_get("/v1/download", h["handle_v1_download"])
    app.router.add_patch("/v1/fs/edit", h["handle_v1_fs_edit"])
    app.router.add_post("/v1/fs/edit/apply", h["handle_v1_fs_edit_apply"])
    app.router.add_post("/v1/fs/edit/rollback", h["handle_v1_fs_edit_rollback"])
    app.router.add_post("/v1/fs/view", h["handle_v1_fs_view"])
    app.router.add_post("/v1/fs/create", h["handle_v1_fs_create"])

    # ---- Dashboard API (auth required) ----
    app.router.add_get("/v1/memory", h["handle_v1_memory"])
    app.router.add_post("/v1/memory", h["handle_v1_memory_set"])
    app.router.add_delete("/v1/memory", h["handle_v1_memory_delete"])
    app.router.add_get("/v1/missions", h["handle_v1_missions"])
    app.router.add_post("/v1/beep", h["handle_v1_beep"])
    app.router.add_get("/v1/doctor", h["handle_v1_doctor"])
    app.router.add_get("/v1/reports", h["handle_v1_reports"])
    app.router.add_get("/v1/browser/search", h["handle_v1_browser_search"])
    app.router.add_get("/v1/browser/read", h["handle_v1_browser_read"])

    # ---- v1.5.0 service/admin/browser utility endpoints ----
    app.router.add_get("/v1/sys/svc", h["handle_v1_sys_svc"])
    app.router.add_get("/v1/service/info", h["handle_v1_service_info"])
    app.router.add_get("/v1/sys/funnel", h["handle_v1_sys_funnel"])
    app.router.add_post("/v1/token/regenerate", h["handle_v1_token_regenerate"])
    app.router.add_post("/v1/tailscale/funnel/{action}", h["handle_v1_tailscale_funnel"])
    app.router.add_get("/v1/tailscale/funnel/{action}", h["handle_v1_tailscale_funnel"])
    app.router.add_post("/v1/cloudflared/tunnel/{action}", h["handle_v1_cloudflared_tunnel"])
    app.router.add_get("/v1/cloudflared/tunnel/{action}", h["handle_v1_cloudflared_tunnel"])
    app.router.add_get("/v1/zerotier/status", h["handle_v1_zerotier_status"])
    app.router.add_post("/v1/zerotier/network/{action}", h["handle_v1_zerotier_network"])
    app.router.add_get("/v1/zerotier/network/{action}", h["handle_v1_zerotier_network"])
    app.router.add_get("/v1/tunnels/status", h["handle_v1_tunnels_status"])
    app.router.add_get("/v1/tunnels/active", h["handle_v1_tunnels_active"])
    app.router.add_post("/v1/tunnels/start", h["handle_v1_tunnels_start"])
    app.router.add_post("/v1/tunnels/stop", h["handle_v1_tunnels_stop"])
    # --- Mobile (Android via ADB) ---
    app.router.add_get("/v1/mobile/devices", h["handle_v1_mobile_devices"])
    app.router.add_get("/v1/mobile/{serial}/info", h["handle_v1_mobile_info"])
    app.router.add_get("/v1/mobile/{serial}/screenshot", h["handle_v1_mobile_screenshot"])
    app.router.add_post("/v1/mobile/{serial}/tap", h["handle_v1_mobile_tap"])
    app.router.add_post("/v1/mobile/{serial}/swipe", h["handle_v1_mobile_swipe"])
    app.router.add_post("/v1/mobile/{serial}/type", h["handle_v1_mobile_type"])
    app.router.add_post("/v1/mobile/{serial}/key", h["handle_v1_mobile_key"])
    app.router.add_get("/v1/mobile/{serial}/key", h["handle_v1_mobile_key"])
    app.router.add_post("/v1/mobile/{serial}/shell", h["handle_v1_mobile_shell"])
    app.router.add_get("/v1/mobile/{serial}/packages", h["handle_v1_mobile_packages"])
    app.router.add_post("/v1/mobile/{serial}/gesture", h["handle_v1_mobile_gesture"])
    app.router.add_get("/v1/mobile/{serial}/gesture", h["handle_v1_mobile_gesture"])
    app.router.add_get("/v1/mobile/{serial}/ui", h["handle_v1_mobile_ui"])
    app.router.add_post("/v1/mobile/{serial}/tap_by", h["handle_v1_mobile_tap_by"])
    app.router.add_post("/v1/restart", h["handle_v1_restart"])
    app.router.add_get("/v1/webhooks", h["handle_v1_webhooks_get"])
    app.router.add_post("/v1/webhooks", h["handle_v1_webhooks_set"])
    app.router.add_get("/v1/config", h["handle_v1_config"])
    app.router.add_get("/v1/browser/dump", h["handle_v1_browser_dump"])
    app.router.add_get("/v1/browser/fetch", h["handle_v1_browser_fetch"])
    app.router.add_get("/v1/browser/head", h["handle_v1_browser_head"])
