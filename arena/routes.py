"""Route registration for the unified bridge app."""
from __future__ import annotations

from collections.abc import Mapping
from typing import Callable

from aiohttp import web


def register_routes(app: web.Application, h: Mapping[str, Callable]) -> None:
    """Register all public API routes without changing route names/paths.

    ``h`` is intentionally a mapping of legacy handler globals at this migration
    stage. A typed HandlerRegistry can replace it once the composition root is
    fully split out of unified_bridge.py.
    """
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
    app.router.add_get("/v1/hwinfo", h["handle_v1_hwinfo"])  # compatibility alias
    app.router.add_get("/v1/inventory", h["handle_v1_inventory"])
    app.router.add_get("/v1/ps", h["handle_v1_ps"])
    app.router.add_get("/v1/audit", h["handle_v1_audit"])
    app.router.add_post("/v1/exec", h["handle_v1_exec"])
    app.router.add_post("/v1/kill", h["handle_v1_kill"])
    app.router.add_post("/v1/upload", h["handle_v1_upload"])
    app.router.add_get("/v1/download", h["handle_v1_download"])

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

    # ---- v1.5.0 new endpoints ----
    app.router.add_get("/v1/sys/svc", h["handle_v1_sys_svc"])
    app.router.add_get("/v1/service/info", h["handle_v1_service_info"])
    app.router.add_get("/v1/sys/funnel", h["handle_v1_sys_funnel"])
    app.router.add_post("/v1/token/regenerate", h["handle_v1_token_regenerate"])
    app.router.add_post("/v1/tailscale/funnel/{action}", h["handle_v1_tailscale_funnel"])
    app.router.add_get("/v1/tailscale/funnel/{action}", h["handle_v1_tailscale_funnel"])
    app.router.add_post("/v1/cloudflared/tunnel/{action}", h["handle_v1_cloudflared_tunnel"])
    app.router.add_get("/v1/cloudflared/tunnel/{action}", h["handle_v1_cloudflared_tunnel"])
    app.router.add_post("/v1/restart", h["handle_v1_restart"])
    app.router.add_get("/v1/webhooks", h["handle_v1_webhooks_get"])
    app.router.add_post("/v1/webhooks", h["handle_v1_webhooks_set"])
    app.router.add_get("/v1/config", h["handle_v1_config"])
    app.router.add_get("/v1/browser/dump", h["handle_v1_browser_dump"])
    app.router.add_get("/v1/browser/fetch", h["handle_v1_browser_fetch"])
    app.router.add_get("/v1/browser/head", h["handle_v1_browser_head"])

    # ---- CDP (Chrome DevTools Protocol) ----
    app.router.add_get("/v1/browser/cdp/status", h["handle_v1_cdp_status"])
    app.router.add_get("/v1/browser/cdp/diag", h["handle_v1_cdp_diag"])
    app.router.add_get("/v1/browser/cdp/raw-info", h["handle_v1_cdp_raw_info"])
    app.router.add_get("/v1/browser/cdp/test-launch", h["handle_v1_cdp_test_launch"])
    app.router.add_get("/v1/browser/cdp/test-ws", h["handle_v1_cdp_test_ws"])
    app.router.add_post("/v1/browser/cdp/connect", h["handle_v1_cdp_connect"])
    app.router.add_post("/v1/browser/cdp/disconnect", h["handle_v1_cdp_disconnect"])
    app.router.add_post("/v1/browser/cdp/navigate", h["handle_v1_cdp_navigate"])
    app.router.add_get("/v1/browser/cdp/screenshot", h["handle_v1_cdp_screenshot"])
    app.router.add_get("/v1/browser/cdp/dom", h["handle_v1_cdp_dom"])
    app.router.add_post("/v1/browser/cdp/eval", h["handle_v1_cdp_eval"])
    app.router.add_post("/v1/browser/cdp/click", h["handle_v1_cdp_click"])
    app.router.add_post("/v1/browser/cdp/type", h["handle_v1_cdp_type"])
    # Desktop automation (v2.4.0)
    app.router.add_get("/v1/desktop/screenshot", h["handle_v1_desktop_screenshot"])
    app.router.add_post("/v1/desktop/click", h["handle_v1_desktop_click"])
    app.router.add_post("/v1/desktop/type", h["handle_v1_desktop_type"])
    app.router.add_post("/v1/desktop/key", h["handle_v1_desktop_key"])
    app.router.add_post("/v1/desktop/mouse", h["handle_v1_desktop_mouse"])
    app.router.add_get("/v1/desktop/windows", h["handle_v1_desktop_windows"])
    app.router.add_get("/v1/desktop/active_window", h["handle_v1_desktop_active_window"])
    app.router.add_post("/v1/desktop/focus", h["handle_v1_desktop_focus"])
    # Desktop control lease (v2.9.0)
    app.router.add_get("/v1/control/status", h["handle_v1_control_status"])
    app.router.add_post("/v1/control/pause", h["handle_v1_control_pause"])
    app.router.add_post("/v1/control/resume", h["handle_v1_control_resume"])
    app.router.add_post("/v1/control/revoke", h["handle_v1_control_revoke"])
    app.router.add_get("/v1/browser/cdp/tabs", h["handle_v1_cdp_tabs"])
    app.router.add_post("/v1/browser/cdp/tabs/new", h["handle_v1_cdp_tabs_new"])
    app.router.add_post("/v1/browser/cdp/tabs/close", h["handle_v1_cdp_tabs_close"])
    app.router.add_post("/v1/browser/cdp/tabs/activate", h["handle_v1_cdp_tabs_activate"])
    app.router.add_get("/v1/browser/cdp/cookies", h["handle_v1_cdp_cookies_get"])
    app.router.add_post("/v1/browser/cdp/cookies", h["handle_v1_cdp_cookies_set"])
    app.router.add_delete("/v1/browser/cdp/cookies", h["handle_v1_cdp_cookies_delete"])
    app.router.add_post("/v1/browser/cdp/cookies/clear", h["handle_v1_cdp_cookies_clear"])
    app.router.add_get("/v1/browser/cdp/cookies/profiles", h["handle_v1_cdp_cookies_profiles"])
    app.router.add_post("/v1/browser/cdp/cookies/profiles", h["handle_v1_cdp_cookies_profiles"])
    app.router.add_post("/v1/browser/cdp/network/start", h["handle_v1_cdp_network_start"])
    app.router.add_post("/v1/browser/cdp/network/stop", h["handle_v1_cdp_network_stop"])
    app.router.add_get("/v1/browser/cdp/network/requests", h["handle_v1_cdp_network_requests"])
    app.router.add_get("/v1/browser/cdp/network/har", h["handle_v1_cdp_network_har"])
    app.router.add_post("/v1/browser/cdp/intercept/start", h["handle_v1_cdp_intercept_start"])
    app.router.add_post("/v1/browser/cdp/intercept/stop", h["handle_v1_cdp_intercept_stop"])
    app.router.add_post("/v1/browser/cdp/intercept/rule", h["handle_v1_cdp_intercept_rule"])
    app.router.add_delete("/v1/browser/cdp/intercept/rule", h["handle_v1_cdp_intercept_rule"])
    app.router.add_get("/v1/browser/cdp/intercept/rules", h["handle_v1_cdp_intercept_rule"])
    app.router.add_get("/v1/browser/cdp/session/check", h["handle_v1_cdp_session_check"])
    app.router.add_post("/v1/browser/cdp/stealth/extract", h["handle_v1_cdp_stealth_extract"])
    app.router.add_post("/v1/browser/cdp/stealth/shot", h["handle_v1_cdp_stealth_shot"])
    app.router.add_get("/v1/browser/cdp/health", h["handle_v1_cdp_health"])

    # Short CDP aliases for agents/tools that infer paths from docs.
    app.router.add_get("/v1/cdp/status", h["handle_v1_cdp_status"])
    app.router.add_get("/v1/cdp/diag", h["handle_v1_cdp_diag"])
    app.router.add_get("/v1/cdp/raw-info", h["handle_v1_cdp_raw_info"])
    app.router.add_get("/v1/cdp/test-launch", h["handle_v1_cdp_test_launch"])
    app.router.add_get("/v1/cdp/test-ws", h["handle_v1_cdp_test_ws"])
    app.router.add_post("/v1/cdp/connect", h["handle_v1_cdp_connect"])
    app.router.add_post("/v1/cdp/disconnect", h["handle_v1_cdp_disconnect"])
    app.router.add_post("/v1/cdp/navigate", h["handle_v1_cdp_navigate"])
    app.router.add_get("/v1/cdp/screenshot", h["handle_v1_cdp_screenshot"])
    app.router.add_get("/v1/cdp/dom", h["handle_v1_cdp_dom"])
    app.router.add_post("/v1/cdp/eval", h["handle_v1_cdp_eval"])
    app.router.add_post("/v1/cdp/click", h["handle_v1_cdp_click"])
    app.router.add_post("/v1/cdp/type", h["handle_v1_cdp_type"])
    app.router.add_get("/v1/cdp/tabs", h["handle_v1_cdp_tabs"])
    app.router.add_post("/v1/cdp/tabs/new", h["handle_v1_cdp_tabs_new"])
    app.router.add_post("/v1/cdp/tabs/close", h["handle_v1_cdp_tabs_close"])
    app.router.add_post("/v1/cdp/tabs/activate", h["handle_v1_cdp_tabs_activate"])
    app.router.add_get("/v1/cdp/cookies", h["handle_v1_cdp_cookies_get"])
    app.router.add_post("/v1/cdp/cookies", h["handle_v1_cdp_cookies_set"])
    app.router.add_delete("/v1/cdp/cookies", h["handle_v1_cdp_cookies_delete"])
    app.router.add_post("/v1/cdp/cookies/clear", h["handle_v1_cdp_cookies_clear"])
    app.router.add_get("/v1/cdp/cookies/profiles", h["handle_v1_cdp_cookies_profiles"])
    app.router.add_post("/v1/cdp/cookies/profiles", h["handle_v1_cdp_cookies_profiles"])
    app.router.add_post("/v1/cdp/network/start", h["handle_v1_cdp_network_start"])
    app.router.add_post("/v1/cdp/network/stop", h["handle_v1_cdp_network_stop"])
    app.router.add_get("/v1/cdp/network/requests", h["handle_v1_cdp_network_requests"])
    app.router.add_get("/v1/cdp/network/har", h["handle_v1_cdp_network_har"])
    app.router.add_post("/v1/cdp/intercept/start", h["handle_v1_cdp_intercept_start"])
    app.router.add_post("/v1/cdp/intercept/stop", h["handle_v1_cdp_intercept_stop"])
    app.router.add_post("/v1/cdp/intercept/rule", h["handle_v1_cdp_intercept_rule"])
    app.router.add_delete("/v1/cdp/intercept/rule", h["handle_v1_cdp_intercept_rule"])
    app.router.add_get("/v1/cdp/intercept/rules", h["handle_v1_cdp_intercept_rule"])
    app.router.add_get("/v1/cdp/session/check", h["handle_v1_cdp_session_check"])
    app.router.add_post("/v1/cdp/stealth/extract", h["handle_v1_cdp_stealth_extract"])
    app.router.add_post("/v1/cdp/stealth/shot", h["handle_v1_cdp_stealth_shot"])
    app.router.add_get("/v1/cdp/health", h["handle_v1_cdp_health"])

    app.router.add_get("/v1/recall", h["handle_v1_recall"])
    app.router.add_get("/v1/recall/digest", h["handle_v1_recall_digest"])
    app.router.add_get("/v1/audit/stats", h["handle_v1_audit_stats"])
    app.router.add_get("/v1/tasks", h["handle_v1_tasks_get"])
    app.router.add_post("/v1/tasks", h["handle_v1_tasks_post"])
    app.router.add_post("/v1/tasks/clean", h["handle_v1_tasks_clean"])
    app.router.add_get("/v1/skills", h["handle_v1_skills"])
    app.router.add_post("/v1/skills/install", h["handle_v1_skills_install"])
    app.router.add_post("/v1/skills/uninstall", h["handle_v1_skills_uninstall"])
    app.router.add_post("/v1/skills/run", h["handle_v1_skills_run"])
    app.router.add_get("/v1/hooks", h["handle_v1_hooks"])
    app.router.add_get("/v1/agents", h["handle_v1_agents"])
    app.router.add_get("/v1/subagents", h["handle_v1_subagents"])
    app.router.add_post("/v1/subagents/spawn", h["handle_v1_subagents_spawn"])
    app.router.add_get("/v1/mission/show", h["handle_v1_mission_show"])
    app.router.add_get("/v1/metrics", h["handle_v1_metrics"])
    app.router.add_get("/v1/logs", h["handle_v1_logs"])

    # ---- Prometheus & API docs (public) ----
    app.router.add_get("/metrics", h["handle_prometheus_metrics"])
    app.router.add_get("/api-docs", h["handle_api_docs"])
    app.router.add_get("/openapi.json", h["handle_api_docs"])  # v2.10.0 alias

    # ---- Browser auto-switch ----
    app.router.add_post("/v1/browser/browse", h["handle_v1_browser_browse"])

    # ---- Phase 3: WebSocket events ----
    app.router.add_get("/v1/events", h["handle_v1_events"])

    # ---- Phase 3: Skills hot-reload ----
    app.router.add_post("/v1/skills/reload", h["handle_v1_skills_reload"])

    # ---- Phase 3: Request/response log ----
    app.router.add_get("/v1/audit/log", h["handle_v1_audit_log"])

    # ---- Phase 3: Watchdog ----
    app.router.add_get("/v1/watchdog", h["handle_v1_watchdog"])
    app.router.add_post("/v1/watchdog", h["handle_v1_watchdog"])

    # ---- Phase 3: Multi-user auth ----
    app.router.add_get("/v1/users", h["handle_v1_users"])
    app.router.add_post("/v1/users", h["handle_v1_users"])
    app.router.add_delete("/v1/users", h["handle_v1_users"])

    # ---- Phase 3: Batch operations ----
    app.router.add_post("/v1/batch", h["handle_v1_batch"])

    # ---- Phase 3: Browser session profiles ----
    app.router.add_get("/v1/profiles", h["handle_v1_profiles"])
    app.router.add_post("/v1/profiles", h["handle_v1_profiles"])
    app.router.add_post("/v1/profiles/{name}/load", h["handle_v1_profiles_load"])

    # ---- Phase 3: Prometheus alerts ----
    app.router.add_get("/v1/alerts", h["handle_v1_alerts"])
    app.router.add_post("/v1/alerts", h["handle_v1_alerts"])

    # ---- Phase 4: Built-in TLS/HTTPS ----
    app.router.add_get("/v1/tls", h["handle_v1_tls"])
    app.router.add_post("/v1/tls", h["handle_v1_tls"])

    # ---- Phase 4: gRPC-style secondary interface ----
    app.router.add_get("/v1/grpc", h["handle_v1_grpc"])
    app.router.add_post("/v1/grpc", h["handle_v1_grpc"])

    # ---- Phase 4: Live Dashboard v2 ----
    app.router.add_get("/gui/v2", h["handle_gui_v2"])

    # ---- Phase 4: Rate Limiting v2 ----
    app.router.add_get("/v1/ratelimit", h["handle_v1_ratelimit"])
    app.router.add_post("/v1/ratelimit", h["handle_v1_ratelimit"])

    # ---- Phase 4: Skill Sandboxing ----
    app.router.add_get("/v1/sandbox", h["handle_v1_sandbox"])
    app.router.add_post("/v1/sandbox", h["handle_v1_sandbox"])

    # ---- Phase 4: Clustering/HA ----
    app.router.add_get("/v1/cluster", h["handle_v1_cluster"])
    app.router.add_post("/v1/cluster", h["handle_v1_cluster"])

    # ---- Phase 4: API Versioning (/v2/) ----
    app.router.add_get("/v2/", h["handle_v2_index"])
    app.router.add_get("/v2/status", h["handle_v2_status"])
    app.router.add_get("/v2/health", h["handle_v2_health"])
    app.router.add_get("/v2/browser/status", h["handle_v2_browser_status"])
    app.router.add_post("/v2/exec", h["handle_v2_exec"])
    app.router.add_get("/v2/deprecations", h["handle_v2_deprecations"])

    # ---- Phase 4: OpenTelemetry Tracing ----
    app.router.add_get("/v1/tracing", h["handle_v1_tracing"])
    app.router.add_post("/v1/tracing", h["handle_v1_tracing"])
    app.router.add_get("/v1/traces/export", h["handle_v1_traces_export"])
    app.router.add_post("/v1/traces/export", h["handle_v1_traces_export"])

    # ---- Dashboard ----
    app.router.add_get("/gui", h["handle_gui"])

    # ---- MCP Streamable HTTP ----
    app.router.add_post("/mcp", h["handle_mcp_post"])
    app.router.add_delete("/mcp", h["handle_mcp_delete"])

    # ---- MCP SSE Legacy ----
    app.router.add_get("/sse", h["handle_sse"])
    app.router.add_post("/messages", h["handle_sse_messages"])

    # ---- MCP WebSocket ----
    app.router.add_get("/ws", h["handle_ws"])

    # ---- Web Gateway ----
    app.router.add_get("/gateway", h["handle_gateway_index"])
    app.router.add_get("/gateway/tools", h["handle_gateway_tools"])
    app.router.add_post("/run", h["handle_gateway_run"])
    app.router.add_post("/tool", h["handle_gateway_tool"])

