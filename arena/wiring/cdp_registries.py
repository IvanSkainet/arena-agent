"""CDP handler wiring extracted from unified_bridge.py."""
from __future__ import annotations

from collections.abc import MutableMapping
from typing import Any, Callable

from arena.wiring.env import RuntimeEnv


def build_cdp_registries(g: MutableMapping[str, Any]) -> dict[str, Callable]:
    """Build CDP handler registries and compatibility helper globals."""
    env = RuntimeEnv(g)
    registry: dict[str, Callable] = {}

    cdp_basic_handler_ctx = env.CdpBasicHandlerContext(
        require_auth=env.require_auth,
        record_request=env._record_request,
        cors_json_response=env._cors_json_response,
        cdp_state=env._cdp_state,
        get_cdp_module=env._get_cdp_module,
        watcher_active=env._cdp_watcher_active,
    )
    cdp_basic_handlers = env.make_cdp_basic_handlers(cdp_basic_handler_ctx)
    env.export_handler_attrs(registry, cdp_basic_handlers, {"handle_v1_cdp_status": "status", "handle_v1_cdp_diag": "diag"})
    registry.update({"_cdp_basic_handler_ctx": cdp_basic_handler_ctx, "_cdp_basic_handlers": cdp_basic_handlers})

    cdp_diagnostic_handler_ctx = env.CdpDiagnosticHandlerContext(
        require_auth=env.require_auth,
        record_request=env._record_request,
        cors_json_response=env._cors_json_response,
        executor=env._EXECUTOR,
        get_cdp_module=env._get_cdp_module,
        log_info=env.log.info,
        log_warning=env.log.warning,
        log_error=env.log.error,
    )
    cdp_diagnostic_handlers = env.make_cdp_diagnostic_handlers(cdp_diagnostic_handler_ctx)
    env.export_handler_attrs(registry, cdp_diagnostic_handlers, {"handle_v1_cdp_raw_info": "raw_info", "handle_v1_cdp_test_launch": "test_launch", "handle_v1_cdp_test_ws": "test_ws"})
    registry.update({"_cdp_diagnostic_handler_ctx": cdp_diagnostic_handler_ctx, "_cdp_diagnostic_handlers": cdp_diagnostic_handlers})

    cdp_session_handler_ctx = env.CdpSessionHandlerContext(
        require_auth=env.require_auth,
        record_request=env._record_request,
        cors_json_response=env._cors_json_response,
        cdp_state=env._cdp_state,
        cdp_connect_lock=env._cdp_connect_lock,
        get_cdp_module=env._get_cdp_module,
        start_cdp_watcher=env._start_cdp_watcher,
        stop_cdp_watcher=env._stop_cdp_watcher,
        emit_event=env.emit_event,
        log_info=env.log.info,
        log_warning=env.log.warning,
    )
    cdp_session_handlers = env.make_cdp_session_handlers(cdp_session_handler_ctx)
    env.export_handler_attrs(registry, cdp_session_handlers, {"handle_v1_cdp_connect": "connect", "handle_v1_cdp_disconnect": "disconnect"})
    registry.update({"_cdp_session_handler_ctx": cdp_session_handler_ctx, "_cdp_session_handlers": cdp_session_handlers})

    async def _cdp_active_tab(tab_id=None):
        """Compatibility wrapper for CDP tab resolution during v3 migration."""
        return await env._cdp_active_tab_impl(
            tab_id,
            cdp_state=env._cdp_state,
            get_cdp_module=env._get_cdp_module,
            cors_json_response=env._cors_json_response,
            log_warning=env.log.warning,
        )

    registry["_cdp_active_tab"] = _cdp_active_tab

    cdp_page_handler_ctx = env.CdpPageHandlerContext(
        require_auth=env.require_auth,
        record_request=env._record_request,
        cors_json_response=env._cors_json_response,
        cdp_state=env._cdp_state,
        cdp_active_tab=_cdp_active_tab,
        default_max_output=env.DEFAULT_MAX_OUTPUT,
        log_debug=env.log.debug,
        log_warning=env.log.warning,
        log_error=env.log.error,
    )
    cdp_page_handlers = env.make_cdp_page_handlers(cdp_page_handler_ctx)
    env.export_handler_attrs(registry, cdp_page_handlers, {"handle_v1_cdp_navigate": "navigate", "handle_v1_cdp_screenshot": "screenshot", "handle_v1_cdp_dom": "dom", "handle_v1_cdp_eval": "eval", "handle_v1_cdp_click": "click", "handle_v1_cdp_type": "type"})
    registry.update({"_cdp_page_handler_ctx": cdp_page_handler_ctx, "_cdp_page_handlers": cdp_page_handlers})

    cdp_tabs_handler_ctx = env.CdpTabsHandlerContext(
        require_auth=env.require_auth,
        record_request=env._record_request,
        cors_json_response=env._cors_json_response,
        cdp_state=env._cdp_state,
        log_debug=env.log.debug,
    )
    cdp_tabs_handlers = env.make_cdp_tabs_handlers(cdp_tabs_handler_ctx)
    env.export_handler_attrs(registry, cdp_tabs_handlers, {"handle_v1_cdp_tabs": "tabs", "handle_v1_cdp_tabs_new": "new", "handle_v1_cdp_tabs_close": "close", "handle_v1_cdp_tabs_activate": "activate"})
    registry.update({"_cdp_tabs_handler_ctx": cdp_tabs_handler_ctx, "_cdp_tabs_handlers": cdp_tabs_handlers})

    cdp_cookies_handler_ctx = env.CdpCookiesHandlerContext(
        require_auth=env.require_auth,
        record_request=env._record_request,
        cors_json_response=env._cors_json_response,
        cdp_state=env._cdp_state,
        cdp_active_tab=_cdp_active_tab,
        get_cdp_module=env._get_cdp_module,
        log_info=env.log.info,
        log_warning=env.log.warning,
        log_error=env.log.error,
    )
    cdp_cookies_handlers = env.make_cdp_cookies_handlers(cdp_cookies_handler_ctx)
    env.export_handler_attrs(registry, cdp_cookies_handlers, {"handle_v1_cdp_cookies_get": "get", "handle_v1_cdp_cookies_set": "set", "handle_v1_cdp_cookies_delete": "delete", "handle_v1_cdp_cookies_clear": "clear", "handle_v1_cdp_cookies_profiles": "profiles"})

    async def _ensure_cookie_manager():
        """Compatibility wrapper for remaining CDP handlers during migration."""
        return await env._cdp_ensure_cookie_manager(cdp_cookies_handler_ctx)

    registry.update({"_cdp_cookies_handler_ctx": cdp_cookies_handler_ctx, "_cdp_cookies_handlers": cdp_cookies_handlers, "_ensure_cookie_manager": _ensure_cookie_manager})

    cdp_network_handler_ctx = env.CdpNetworkHandlerContext(
        require_auth=env.require_auth,
        record_request=env._record_request,
        cors_json_response=env._cors_json_response,
        cdp_state=env._cdp_state,
        cdp_active_tab=_cdp_active_tab,
        get_cdp_module=env._get_cdp_module,
    )
    cdp_network_handlers = env.make_cdp_network_handlers(cdp_network_handler_ctx)
    env.export_handler_attrs(registry, cdp_network_handlers, {"handle_v1_cdp_network_start": "start", "handle_v1_cdp_network_stop": "stop", "handle_v1_cdp_network_requests": "requests", "handle_v1_cdp_network_har": "har"})
    registry.update({"_cdp_network_handler_ctx": cdp_network_handler_ctx, "_cdp_network_handlers": cdp_network_handlers})

    cdp_intercept_handler_ctx = env.CdpInterceptHandlerContext(
        require_auth=env.require_auth,
        record_request=env._record_request,
        cors_json_response=env._cors_json_response,
        cdp_state=env._cdp_state,
        cdp_active_tab=_cdp_active_tab,
        get_cdp_module=env._get_cdp_module,
    )
    cdp_intercept_handlers = env.make_cdp_intercept_handlers(cdp_intercept_handler_ctx)
    env.export_handler_attrs(registry, cdp_intercept_handlers, {"handle_v1_cdp_intercept_start": "start", "handle_v1_cdp_intercept_stop": "stop", "handle_v1_cdp_intercept_rule": "rule"})
    registry.update({"_cdp_intercept_handler_ctx": cdp_intercept_handler_ctx, "_cdp_intercept_handlers": cdp_intercept_handlers})

    cdp_advanced_handler_ctx = env.CdpAdvancedHandlerContext(
        require_auth=env.require_auth,
        record_request=env._record_request,
        cors_json_response=env._cors_json_response,
        cdp_state=env._cdp_state,
        ensure_cookie_manager=_ensure_cookie_manager,
        watcher_active=env._cdp_watcher_active,
        bridge_start_time=env.BRIDGE_METRICS["start_time"],
    )
    cdp_advanced_handlers = env.make_cdp_advanced_handlers(cdp_advanced_handler_ctx)
    env.export_handler_attrs(registry, cdp_advanced_handlers, {"handle_v1_cdp_session_check": "session_check", "handle_v1_cdp_stealth_extract": "stealth_extract", "handle_v1_cdp_stealth_shot": "stealth_shot", "handle_v1_cdp_health": "health"})

    async def _cdp_get_active_browser():
        """Compatibility wrapper for remaining code during CDP migration."""
        return await env._cdp_get_active_browser_from_context(cdp_advanced_handler_ctx)

    registry.update({"_cdp_advanced_handler_ctx": cdp_advanced_handler_ctx, "_cdp_advanced_handlers": cdp_advanced_handlers, "_cdp_get_active_browser": _cdp_get_active_browser})
    return registry


__all__ = ["build_cdp_registries"]
