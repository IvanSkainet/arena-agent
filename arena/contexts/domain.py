"""Handler context dataclasses for domain domains."""
from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import Executor
from dataclasses import dataclass
from typing import Any

from aiohttp import web


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
    subagent_spawn_sync: Callable[[dict[str, Any]], dict[str, Any]]
    audit: Callable[[dict[str, Any]], None]


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

__all__ = ['TaskHandlerContext', 'SkillHandlerContext', 'ResourceHandlerContext', 'MemoryHandlerContext']
