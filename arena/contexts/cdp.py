"""Handler context dataclasses for cdp domains."""
from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import Executor
from dataclasses import dataclass
from typing import Any

from aiohttp import web


@dataclass(frozen=True)
class CdpBasicHandlerContext:
    """Dependencies for lightweight CDP status/diagnostic handlers."""

    require_auth: Callable[[web.Request], web.Response | None]
    record_request: Callable[..., None]
    cors_json_response: Callable[..., web.Response]
    cdp_state: dict[str, Any]
    get_cdp_module: Callable[[], Any]
    watcher_active: Callable[[], bool]


@dataclass(frozen=True)
class CdpDiagnosticHandlerContext:
    """Dependencies for CDP launch/WebSocket diagnostic handlers."""

    require_auth: Callable[[web.Request], web.Response | None]
    record_request: Callable[..., None]
    cors_json_response: Callable[..., web.Response]
    executor: Executor
    get_cdp_module: Callable[[], Any]
    log_info: Callable[..., None]
    log_warning: Callable[..., None]
    log_error: Callable[..., None]


@dataclass(frozen=True)
class CdpSessionHandlerContext:
    """Dependencies for CDP connect/disconnect session lifecycle handlers."""

    require_auth: Callable[[web.Request], web.Response | None]
    record_request: Callable[..., None]
    cors_json_response: Callable[..., web.Response]
    cdp_state: dict[str, Any]
    cdp_connect_lock: Any
    get_cdp_module: Callable[[], Any]
    start_cdp_watcher: Callable[[], Any]
    stop_cdp_watcher: Callable[[], Any]
    emit_event: Callable[[str, dict | None], Any]
    log_info: Callable[..., None]
    log_warning: Callable[..., None]


@dataclass(frozen=True)
class CdpPageHandlerContext:
    """Dependencies for CDP page action handlers."""

    require_auth: Callable[[web.Request], web.Response | None]
    record_request: Callable[..., None]
    cors_json_response: Callable[..., web.Response]
    cdp_state: dict[str, Any]
    cdp_active_tab: Callable[..., Any]
    default_max_output: int
    log_debug: Callable[..., None]
    log_warning: Callable[..., None]
    log_error: Callable[..., None]


@dataclass(frozen=True)
class CdpTabsHandlerContext:
    """Dependencies for CDP tab management handlers."""

    require_auth: Callable[[web.Request], web.Response | None]
    record_request: Callable[..., None]
    cors_json_response: Callable[..., web.Response]
    cdp_state: dict[str, Any]
    log_debug: Callable[..., None]


@dataclass(frozen=True)
class CdpCookiesHandlerContext:
    """Dependencies for CDP cookie/profile handlers."""

    require_auth: Callable[[web.Request], web.Response | None]
    record_request: Callable[..., None]
    cors_json_response: Callable[..., web.Response]
    cdp_state: dict[str, Any]
    cdp_active_tab: Callable[..., Any]
    get_cdp_module: Callable[[], Any]
    log_info: Callable[..., None]
    log_warning: Callable[..., None]
    log_error: Callable[..., None]


@dataclass(frozen=True)
class CdpNetworkHandlerContext:
    """Dependencies for CDP network monitoring handlers."""

    require_auth: Callable[[web.Request], web.Response | None]
    record_request: Callable[..., None]
    cors_json_response: Callable[..., web.Response]
    cdp_state: dict[str, Any]
    cdp_active_tab: Callable[..., Any]
    get_cdp_module: Callable[[], Any]


@dataclass(frozen=True)
class CdpInterceptHandlerContext:
    """Dependencies for CDP network interception handlers."""

    require_auth: Callable[[web.Request], web.Response | None]
    record_request: Callable[..., None]
    cors_json_response: Callable[..., web.Response]
    cdp_state: dict[str, Any]
    cdp_active_tab: Callable[..., Any]
    get_cdp_module: Callable[[], Any]


@dataclass(frozen=True)
class CdpAdvancedHandlerContext:
    """Dependencies for CDP session health, health dashboard, and stealth helpers."""

    require_auth: Callable[[web.Request], web.Response | None]
    record_request: Callable[..., None]
    cors_json_response: Callable[..., web.Response]
    cdp_state: dict[str, Any]
    ensure_cookie_manager: Callable[[], Any]
    watcher_active: Callable[[], bool]
    bridge_start_time: float

__all__ = ['CdpBasicHandlerContext', 'CdpDiagnosticHandlerContext', 'CdpSessionHandlerContext', 'CdpPageHandlerContext', 'CdpTabsHandlerContext', 'CdpCookiesHandlerContext', 'CdpNetworkHandlerContext', 'CdpInterceptHandlerContext', 'CdpAdvancedHandlerContext']
