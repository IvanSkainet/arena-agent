"""Legacy service and browser handler wiring."""
from __future__ import annotations

from collections.abc import MutableMapping
from typing import Any, Callable

from arena.wiring.env import RuntimeEnv


def build_service_browser_registries(g: MutableMapping[str, Any]) -> dict[str, Callable]:
    """Build service/capabilities and browser fetch/browse handler registries."""
    env = RuntimeEnv(g)
    registry: dict[str, Callable] = {}

    service_handler_registry = env.build_service_handlers(env.ServiceWiringContext(
        require_auth=env.require_auth,
        record_request=env._record_request,
        cors_json_response=env._cors_json_response,
        executor=env._EXECUTOR,
        service_info_sync=env._service_info_sync,
        sys_svc_sync=env._sys_svc_sync,
        capabilities_sync=g["_capabilities_sync"],
        spawn_respawn_helper=env._spawn_respawn_helper,
        audit=env.audit,
    ))
    registry.update(service_handler_registry)

    browser_fetch_handler_ctx = env.BrowserFetchHandlerContext(
        require_auth=env.require_auth,
        record_request=env._record_request,
        cors_json_response=env._cors_json_response,
        executor=env._EXECUTOR,
        browser_search_sync=env._browser_search_sync,
        browser_read_sync=env._browser_read_sync,
        browser_dump_sync=env._browser_dump_sync,
        browser_fetch_sync=env._browser_fetch_sync,
        browser_head_sync=env._browser_head_sync,
    )
    browser_fetch_handlers = env.make_browser_fetch_handlers(browser_fetch_handler_ctx)
    env.export_handler_attrs(
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

    browser_browse_handler_ctx = env.BrowserBrowseHandlerContext(
        require_auth=env.require_auth,
        record_request=env._record_request,
        cors_json_response=env._cors_json_response,
        app_dir=env.APP_DIR,
        cdp_state=env._cdp_state,
        get_cdp_module=env._get_cdp_module,
        start_cdp_watcher=env._start_cdp_watcher,
    )
    browser_browse_handlers = env.make_browser_browse_handlers(browser_browse_handler_ctx)
    env.export_handler_attrs(registry, browser_browse_handlers, {"handle_v1_browser_browse": "browse"})
    registry.update({
        "_browser_fetch_handler_ctx": browser_fetch_handler_ctx,
        "_browser_fetch_handlers": browser_fetch_handlers,
        "_browser_browse_handler_ctx": browser_browse_handler_ctx,
        "_browser_browse_handlers": browser_browse_handlers,
    })
    return registry


__all__ = ["build_service_browser_registries"]
