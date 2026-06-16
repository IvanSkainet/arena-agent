"""Handler context dataclasses for browser domains."""
from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import Executor
from dataclasses import dataclass
from typing import Any

from aiohttp import web


@dataclass(frozen=True)
class BrowserFetchHandlerContext:
    """Dependencies for non-CDP browser/fetch handlers."""

    require_auth: Callable[[web.Request], web.Response | None]
    record_request: Callable[..., None]
    cors_json_response: Callable[..., web.Response]
    executor: Executor
    browser_search_sync: Callable[[str, int], dict[str, Any]]
    browser_read_sync: Callable[[str], dict[str, Any]]
    browser_dump_sync: Callable[[str], dict[str, Any]]
    browser_fetch_sync: Callable[[str], dict[str, Any]]
    browser_head_sync: Callable[[str], dict[str, Any]]


@dataclass(frozen=True)
class BrowserBrowseHandlerContext:
    """Dependencies for /v1/browser/browse.

    The endpoint is intentionally kept outside the CDP package for now: it is a
    high-level router that auto-selects BrowserAct or the existing CDP runtime.
    """

    require_auth: Callable[[web.Request], web.Response | None]
    record_request: Callable[..., None]
    cors_json_response: Callable[..., web.Response]
    app_dir: Any
    cdp_state: dict[str, Any]
    get_cdp_module: Callable[[], Any]
    start_cdp_watcher: Callable[[], Any]


@dataclass(frozen=True)
class ProfileHandlerContext:
    """Dependencies for browser session profile handlers."""

    require_auth: Callable[[web.Request], web.Response | None]
    record_request: Callable[..., None]
    cors_json_response: Callable[..., web.Response]
    profiles_dir: Any
    ensure_profiles_dir: Callable[[], Any]
    cdp_state: dict[str, Any]
    cdp_active_tab: Callable[..., Any]
    version: str
    utc_now: Callable[[], str]
    audit: Callable[[dict[str, Any]], None]
    emit_event: Callable[[str, dict | None], Any]
    log_warning: Callable[..., None]

__all__ = ['BrowserFetchHandlerContext', 'BrowserBrowseHandlerContext', 'ProfileHandlerContext']
