# ruff: noqa: F821
"""Legacy service and browser handler wiring."""
from __future__ import annotations

from collections.abc import MutableMapping
from typing import Any, Callable


def build_service_browser_registries(g: MutableMapping[str, Any]) -> dict[str, Callable]:
    """Build service/capabilities and browser fetch/browse handler registries."""
    globals().update(g)
    registry: dict[str, Callable] = {}

    service_handler_registry = build_service_handlers(ServiceWiringContext(
        require_auth=require_auth,
        record_request=_record_request,
        cors_json_response=_cors_json_response,
        executor=_EXECUTOR,
        service_info_sync=_service_info_sync,
        sys_svc_sync=_sys_svc_sync,
        capabilities_sync=g["_capabilities_sync"],
        spawn_respawn_helper=_spawn_respawn_helper,
        audit=audit,
    ))
    registry.update(service_handler_registry)

    browser_fetch_handler_ctx = BrowserFetchHandlerContext(
        require_auth=require_auth,
        record_request=_record_request,
        cors_json_response=_cors_json_response,
        executor=_EXECUTOR,
        browser_search_sync=_browser_search_sync,
        browser_read_sync=_browser_read_sync,
        browser_dump_sync=_browser_dump_sync,
        browser_fetch_sync=_browser_fetch_sync,
        browser_head_sync=_browser_head_sync,
    )
    browser_fetch_handlers = make_browser_fetch_handlers(browser_fetch_handler_ctx)
    export_handler_attrs(
        registry,
        browser_fetch_handlers,
        {
            "handle_v1_browser_search": "search",
            "handle_v1_browser_read": "read",
            "handle_v1_browser_dump": "dump",
            "handle_v1_browser_fetch": "fetch",
            "handle_v1_browser_head": "head",
        },
    )

    browser_browse_handler_ctx = BrowserBrowseHandlerContext(
        require_auth=require_auth,
        record_request=_record_request,
        cors_json_response=_cors_json_response,
        app_dir=APP_DIR,
        cdp_state=_cdp_state,
        get_cdp_module=_get_cdp_module,
        start_cdp_watcher=_start_cdp_watcher,
    )
    browser_browse_handlers = make_browser_browse_handlers(browser_browse_handler_ctx)
    export_handler_attrs(registry, browser_browse_handlers, {"handle_v1_browser_browse": "browse"})
    registry.update({
        "_browser_fetch_handler_ctx": browser_fetch_handler_ctx,
        "_browser_fetch_handlers": browser_fetch_handlers,
        "_browser_browse_handler_ctx": browser_browse_handler_ctx,
        "_browser_browse_handlers": browser_browse_handlers,
    })
    return registry


__all__ = ["build_service_browser_registries"]
