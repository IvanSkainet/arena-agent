"""Shared handler context objects for modular API handlers."""
from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import Executor
from dataclasses import dataclass
from typing import Any

from aiohttp import web


@dataclass(frozen=True)
class HandlerContext:
    """Dependencies injected into extracted aiohttp handlers.

    Keeping these dependencies explicit avoids importing the monolith from
    handler modules and makes future tests/refactors substantially easier.
    """

    require_auth: Callable[[web.Request], web.Response | None]
    record_request: Callable[..., None]
    cors_json_response: Callable[..., web.Response]
    executor: Executor
    slow_executor: Executor
    inventory_sync: Callable[..., dict[str, Any]]
    hardware_sync: Callable[..., dict[str, Any]]


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
class TaskHandlerContext:
    """Dependencies for task queue API handlers."""

    require_auth: Callable[[web.Request], web.Response | None]
    record_request: Callable[..., None]
    cors_json_response: Callable[..., web.Response]
    executor: Executor
    tasks_list_sync: Callable[..., dict[str, Any]]
    task_submit_sync: Callable[[dict[str, Any]], dict[str, Any]]
    tasks_clean_sync: Callable[[], dict[str, Any]]
    audit: Callable[[dict[str, Any]], None]


@dataclass(frozen=True)
class SkillHandlerContext:
    """Dependencies for skills API handlers."""

    require_auth: Callable[[web.Request], web.Response | None]
    record_request: Callable[..., None]
    cors_json_response: Callable[..., web.Response]
    executor: Executor
    skills_list_with_cache: Callable[[], dict[str, Any]]
    skills_cache_reset: Callable[[], None]
    skill_install_sync: Callable[[str, str], dict[str, Any]]
    skill_uninstall_sync: Callable[[str], dict[str, Any]]
    skills_run_sync: Callable[[str, list[str], dict[str, Any] | None], dict[str, Any]]
    skill_path_is_safe: Callable[[str], bool]
    audit: Callable[[dict[str, Any]], None]
    log_info: Callable[..., None]


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
class ResourceHandlerContext:
    """Dependencies for resource listing handlers."""

    require_auth: Callable[[web.Request], web.Response | None]
    record_request: Callable[..., None]
    cors_json_response: Callable[..., web.Response]
    executor: Executor
    list_missions_sync: Callable[[], list[dict[str, Any]]]
    list_reports_sync: Callable[[], list[dict[str, Any]]]
    hooks_list_sync: Callable[[], dict[str, Any]]
    agents_list_sync: Callable[[], dict[str, Any]]
    subagents_list_sync: Callable[[], dict[str, Any]]
    mission_show_sync: Callable[[str], dict[str, Any]]


@dataclass(frozen=True)
class MemoryHandlerContext:
    """Dependencies for memory/recall API handlers."""

    require_auth: Callable[[web.Request], web.Response | None]
    record_request: Callable[..., None]
    cors_json_response: Callable[..., web.Response]
    executor: Executor
    search_facts_paged: Callable[..., tuple[int, list[dict[str, Any]]]]
    write_fact: Callable[[dict[str, Any]], None]
    delete_fact: Callable[[str], bool]
    recall_sync: Callable[[str, int], dict[str, Any]]
    recall_digest_sync: Callable[[], dict[str, Any]]
    audit: Callable[[dict[str, Any]], None]
    utc_now: Callable[[], str]


@dataclass(frozen=True)
class ObservabilityHandlerContext:
    """Dependencies for audit/request-log/webhook handlers."""

    require_auth: Callable[[web.Request], web.Response | None]
    record_request: Callable[..., None]
    cors_json_response: Callable[..., web.Response]
    executor: Executor
    audit_path: Any
    request_log_file: Any
    read_tail: Callable[..., list[str]]
    read_request_log: Callable[..., list[dict[str, Any]]]
    audit_stats_sync: Callable[[], dict[str, Any]]
    load_webhooks: Callable[[], dict[str, Any]]
    save_webhooks: Callable[[dict[str, Any]], None]
    normalize_webhooks_config: Callable[[dict[str, Any]], tuple[dict[str, Any] | None, str | None]]
    audit: Callable[[dict[str, Any]], None]
