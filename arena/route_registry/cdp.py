"""CDP canonical and short-alias route registration."""
from __future__ import annotations

from collections.abc import Callable, Mapping

from aiohttp import web


def _register_cdp_prefix(app: web.Application, h: Mapping[str, Callable], prefix: str) -> None:
    app.router.add_get(f"{prefix}/status", h["handle_v1_cdp_status"])
    app.router.add_get(f"{prefix}/diag", h["handle_v1_cdp_diag"])
    app.router.add_get(f"{prefix}/raw-info", h["handle_v1_cdp_raw_info"])
    app.router.add_get(f"{prefix}/test-launch", h["handle_v1_cdp_test_launch"])
    app.router.add_get(f"{prefix}/test-ws", h["handle_v1_cdp_test_ws"])
    app.router.add_post(f"{prefix}/connect", h["handle_v1_cdp_connect"])
    app.router.add_post(f"{prefix}/disconnect", h["handle_v1_cdp_disconnect"])
    app.router.add_post(f"{prefix}/navigate", h["handle_v1_cdp_navigate"])
    app.router.add_get(f"{prefix}/screenshot", h["handle_v1_cdp_screenshot"])
    app.router.add_get(f"{prefix}/dom", h["handle_v1_cdp_dom"])
    app.router.add_post(f"{prefix}/eval", h["handle_v1_cdp_eval"])
    app.router.add_post(f"{prefix}/click", h["handle_v1_cdp_click"])
    app.router.add_post(f"{prefix}/type", h["handle_v1_cdp_type"])
    app.router.add_get(f"{prefix}/tabs", h["handle_v1_cdp_tabs"])
    app.router.add_post(f"{prefix}/tabs/new", h["handle_v1_cdp_tabs_new"])
    app.router.add_post(f"{prefix}/tabs/close", h["handle_v1_cdp_tabs_close"])
    app.router.add_post(f"{prefix}/tabs/activate", h["handle_v1_cdp_tabs_activate"])
    app.router.add_get(f"{prefix}/cookies", h["handle_v1_cdp_cookies_get"])
    app.router.add_post(f"{prefix}/cookies", h["handle_v1_cdp_cookies_set"])
    app.router.add_delete(f"{prefix}/cookies", h["handle_v1_cdp_cookies_delete"])
    app.router.add_post(f"{prefix}/cookies/clear", h["handle_v1_cdp_cookies_clear"])
    app.router.add_get(f"{prefix}/cookies/profiles", h["handle_v1_cdp_cookies_profiles"])
    app.router.add_post(f"{prefix}/cookies/profiles", h["handle_v1_cdp_cookies_profiles"])
    app.router.add_post(f"{prefix}/network/start", h["handle_v1_cdp_network_start"])
    app.router.add_post(f"{prefix}/network/stop", h["handle_v1_cdp_network_stop"])
    app.router.add_get(f"{prefix}/network/requests", h["handle_v1_cdp_network_requests"])
    app.router.add_get(f"{prefix}/network/har", h["handle_v1_cdp_network_har"])
    app.router.add_post(f"{prefix}/intercept/start", h["handle_v1_cdp_intercept_start"])
    app.router.add_post(f"{prefix}/intercept/stop", h["handle_v1_cdp_intercept_stop"])
    app.router.add_post(f"{prefix}/intercept/rule", h["handle_v1_cdp_intercept_rule"])
    app.router.add_delete(f"{prefix}/intercept/rule", h["handle_v1_cdp_intercept_rule"])
    app.router.add_get(f"{prefix}/intercept/rules", h["handle_v1_cdp_intercept_rule"])
    app.router.add_get(f"{prefix}/session/check", h["handle_v1_cdp_session_check"])
    app.router.add_post(f"{prefix}/stealth/extract", h["handle_v1_cdp_stealth_extract"])
    app.router.add_post(f"{prefix}/stealth/shot", h["handle_v1_cdp_stealth_shot"])
    app.router.add_get(f"{prefix}/health", h["handle_v1_cdp_health"])


def register_cdp_routes(app: web.Application, h: Mapping[str, Callable]) -> None:
    _register_cdp_prefix(app, h, "/v1/browser/cdp")
    _register_cdp_prefix(app, h, "/v1/cdp")
