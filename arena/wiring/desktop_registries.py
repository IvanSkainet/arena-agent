"""desktop and control lease handler wiring."""
from __future__ import annotations

from collections.abc import MutableMapping
from typing import Any, Callable

from arena.wiring.env import RuntimeEnv



def build_desktop_registries(g: MutableMapping[str, Any]) -> dict[str, Callable]:
    """Build desktop automation and control lease registries."""
    env = RuntimeEnv(g)
    registry: dict[str, Callable] = {}

    desktop_handler_ctx = env.DesktopHandlerContext(
        require_auth=env.require_auth,
        record_request=env._record_request,
        cors_json_response=env._cors_json_response,
        control_check=env._control_check,
        control_record_agent_action=env._control_record_agent_action,
        desktop_exec=env._desktop_exec,
        detect_desktop_env=env._detect_desktop_env,
        get_active_window=env._get_active_window,
        kwin_windows_via_script=env._kwin_windows_via_script,
        capture_screenshot=env.capture_desktop_screenshot,
        ocr_desktop=env.ocr_desktop,
        kwin_focus_window=env.kwin_focus_window_via_script,
        focus_window=env.focus_window,
        audit=env.audit,
    )
    desktop_handlers = env.make_desktop_handlers(desktop_handler_ctx)
    env.export_handler_attrs(
        registry,
        desktop_handlers,
        {
            "handle_v1_desktop_screenshot": "screenshot",
            "handle_v1_desktop_displays": "displays",
            "handle_v1_desktop_click": "click",
            "handle_v1_desktop_type": "type",
            "handle_v1_desktop_key": "key",
            "handle_v1_desktop_mouse": "mouse",
            "handle_v1_desktop_windows": "windows",
            "handle_v1_desktop_active_window": "active_window",
            "handle_v1_desktop_focus": "focus",
            "handle_v1_desktop_window_action": "window_action",
            "handle_v1_desktop_ocr": "ocr",
            "handle_v1_desktop_find_text": "find_text",
            "handle_v1_desktop_click_text": "click_text",
        },
    )
    registry.update({"_desktop_handler_ctx": desktop_handler_ctx, "_desktop_handlers": desktop_handlers})

    control_lease_handler_ctx = env.ControlLeaseHandlerContext(
        require_auth=env.require_auth,
        record_request=env._record_request,
        cors_json_response=env._cors_json_response,
        control_state=env._control_state,
        control_lock=env._control_lock,
        utc_now=env.utc_now,
        log_info=env.log.info,
        log_warning=env.log.warning,
    )
    control_lease_handlers = env.make_control_lease_handlers(control_lease_handler_ctx)
    env.export_handler_attrs(registry, control_lease_handlers, {"handle_v1_control_status": "status", "handle_v1_control_pause": "pause", "handle_v1_control_resume": "resume", "handle_v1_control_revoke": "revoke"})
    registry.update({"_control_lease_handler_ctx": control_lease_handler_ctx, "_control_lease_handlers": control_lease_handlers})
    return registry


__all__ = ["build_desktop_registries"]
