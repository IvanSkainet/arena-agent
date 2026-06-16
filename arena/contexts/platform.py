"""Handler context dataclasses for platform domains."""
from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import Executor
from dataclasses import dataclass
from typing import Any

from aiohttp import web


@dataclass(frozen=True)
class ServiceHandlerContext:
    """Dependencies for service/capabilities/restart handlers."""

    require_auth: Callable[[web.Request], web.Response | None]
    record_request: Callable[..., None]
    cors_json_response: Callable[..., web.Response]
    executor: Executor
    service_info_sync: Callable[[], dict[str, Any]]
    sys_svc_sync: Callable[[], dict[str, Any]]
    capabilities_sync: Callable[[], dict[str, Any]]
    spawn_respawn_helper: Callable[[int], tuple[bool, str]]
    audit: Callable[[dict[str, Any]], None]


@dataclass(frozen=True)
class DesktopHandlerContext:
    """Dependencies for desktop automation API handlers."""

    require_auth: Callable[[web.Request], web.Response | None]
    record_request: Callable[..., None]
    cors_json_response: Callable[..., web.Response]
    control_check: Callable[[], dict | None]
    control_record_agent_action: Callable[[], None]
    desktop_exec: Callable[..., Any]
    detect_desktop_env: Callable[[], dict[str, Any]]
    get_active_window: Callable[[], Any]
    kwin_windows_via_script: Callable[[], Any]
    capture_screenshot: Callable[..., Any]
    focus_window: Callable[..., Any]
    audit: Callable[[dict[str, Any]], None]


@dataclass(frozen=True)
class ControlLeaseHandlerContext:
    """Dependencies for desktop control lease handlers."""

    require_auth: Callable[[web.Request], web.Response | None]
    record_request: Callable[..., None]
    cors_json_response: Callable[..., web.Response]
    control_state: dict[str, Any]
    control_lock: Any
    utc_now: Callable[[], str]
    log_info: Callable[..., None]
    log_warning: Callable[..., None]


@dataclass(frozen=True)
class SystemHandlerContext:
    """Dependencies for simple system/version/status/config/doctor handlers."""

    require_auth: Callable[[web.Request], web.Response | None]
    record_request: Callable[..., None]
    cors_json_response: Callable[..., web.Response]
    executor: Executor
    common_status: Callable[[dict[str, Any]], dict[str, Any]]
    version: str
    clean_platform_name: Callable[[], str]
    doctor_sync: Callable[[str], dict[str, Any]]
    sysinfo_sync: Callable[[Any], dict[str, Any]]
    play_beep_sync: Callable[[str, int, int], dict[str, Any]]


@dataclass(frozen=True)
class UserHandlerContext:
    """Dependencies for user-management handlers."""

    require_auth: Callable[[web.Request], web.Response | None]
    record_request: Callable[..., None]
    cors_json_response: Callable[..., web.Response]
    check_auth_with_role: Callable[[web.Request], tuple[bool, str]]
    list_users: Callable[[str], list[dict[str, Any]]]
    add_or_update_user: Callable[..., None]
    remove_user: Callable[[str], bool]
    token_generator: Callable[[int], str]
    audit: Callable[[dict[str, Any]], None]
    log_info: Callable[..., None]


@dataclass(frozen=True)
class AdminHandlerContext:
    """Dependencies for token/tunnel/funnel admin handlers."""

    require_auth: Callable[[web.Request], web.Response | None]
    record_request: Callable[..., None]
    cors_json_response: Callable[..., web.Response]
    executor: Executor
    audit: Callable[[dict[str, Any]], None]
    default_token_file: Any
    root_agent: Any
    subprocess_kwargs: Callable[[], dict[str, Any]]

__all__ = ['ServiceHandlerContext', 'DesktopHandlerContext', 'ControlLeaseHandlerContext', 'SystemHandlerContext', 'UserHandlerContext', 'AdminHandlerContext']
