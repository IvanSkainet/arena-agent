# ruff: noqa: F821
"""Legacy desktop and control lease handler wiring."""
from __future__ import annotations

from collections.abc import MutableMapping
from typing import Any, Callable


def build_desktop_registries(g: MutableMapping[str, Any]) -> dict[str, Callable]:
    """Build desktop automation and control lease registries."""
    globals().update(g)
    registry: dict[str, Callable] = {}

    desktop_handler_ctx = DesktopHandlerContext(
        require_auth=require_auth,
        record_request=_record_request,
        cors_json_response=_cors_json_response,
        control_check=_control_check,
        control_record_agent_action=_control_record_agent_action,
        desktop_exec=_desktop_exec,
        detect_desktop_env=_detect_desktop_env,
        get_active_window=_get_active_window,
        kwin_windows_via_script=_kwin_windows_via_script,
        capture_screenshot=capture_desktop_screenshot,
        focus_window=focus_window,
        audit=audit,
    )
    desktop_handlers = make_desktop_handlers(desktop_handler_ctx)
    export_handler_attrs(registry, desktop_handlers, {"handle_v1_desktop_screenshot": "screenshot", "handle_v1_desktop_click": "click", "handle_v1_desktop_type": "type", "handle_v1_desktop_key": "key", "handle_v1_desktop_mouse": "mouse", "handle_v1_desktop_windows": "windows", "handle_v1_desktop_active_window": "active_window", "handle_v1_desktop_focus": "focus"})
    registry.update({"_desktop_handler_ctx": desktop_handler_ctx, "_desktop_handlers": desktop_handlers})

    control_lease_handler_ctx = ControlLeaseHandlerContext(
        require_auth=require_auth,
        record_request=_record_request,
        cors_json_response=_cors_json_response,
        control_state=_control_state,
        control_lock=_control_lock,
        utc_now=utc_now,
        log_info=log.info,
        log_warning=log.warning,
    )
    control_lease_handlers = make_control_lease_handlers(control_lease_handler_ctx)
    export_handler_attrs(registry, control_lease_handlers, {"handle_v1_control_status": "status", "handle_v1_control_pause": "pause", "handle_v1_control_resume": "resume", "handle_v1_control_revoke": "revoke"})
    registry.update({"_control_lease_handler_ctx": control_lease_handler_ctx, "_control_lease_handlers": control_lease_handlers})
    return registry


__all__ = ["build_desktop_registries"]
