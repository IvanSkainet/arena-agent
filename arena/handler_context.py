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
class FileHandlerContext:
    """Dependencies for file upload/download handlers."""

    require_auth: Callable[[web.Request], web.Response | None]
    record_request: Callable[..., None]
    cors_json_response: Callable[..., web.Response]
    audit: Callable[[dict[str, Any]], None]
    home: Any
    bridge_py: Any


@dataclass(frozen=True)
class ExecHandlerContext:
    """Dependencies for exec/process API handlers."""

    require_auth: Callable[[web.Request], web.Response | None]
    record_request: Callable[..., None]
    cors_json_response: Callable[..., web.Response]
    audit: Callable[[dict[str, Any]], None]
    blocked_reason: Callable[[str], str | None]
    control_check: Callable[[], dict | None]
    is_input_injection_cmd: Callable[[str], str | None]
    first_word: Callable[[str], str]
    under_root: Callable[[Any, Any], bool]
    decode_output: Callable[[bytes], str]
    run_shell_command: Callable[..., Any]
    active_processes: dict[str, dict[str, Any]]
    active_processes_snapshot: Callable[..., list[dict[str, Any]]]
    cautious_allow: set[str]
    default_max_output: int

@dataclass(frozen=True)
class GatewayHandlerContext:
    """Dependencies for Web Gateway handlers."""

    require_auth: Callable[[web.Request], web.Response | None]
    record_request: Callable[..., None]
    cors_json_response: Callable[..., web.Response]
    executor: Executor
    handle_rpc: Callable[[dict[str, Any]], dict[str, Any] | None]
    subprocess_kwargs: Callable[[], dict[str, Any]]

@dataclass(frozen=True)
class TracingHandlerContext:
    """Dependencies for OpenTelemetry tracing handlers."""

    require_auth: Callable[[web.Request], web.Response | None]
    record_request: Callable[..., None]
    cors_json_response: Callable[..., web.Response]
    version: str
    log_info: Callable[..., None]

@dataclass(frozen=True)
class ApiV2HandlerContext:
    """Dependencies for v2 compatibility API handlers."""

    require_auth: Callable[[web.Request], web.Response | None]
    record_request: Callable[..., None]
    cors_json_response: Callable[..., web.Response]
    version: str
    metrics: dict[str, Any]
    cdp_state: dict[str, Any]
    watchdog_state: dict[str, Any]
    cluster_state: dict[str, Any]
    cluster_config: dict[str, Any]
    tls_config: dict[str, Any]
    profiles_dir: Any
    sandbox_config: dict[str, Any]
    blocked_reason: Callable[[str], str | None]
    first_word: Callable[[str], str]
    decode_output: Callable[[bytes], str]
    run_sandboxed: Callable[..., Any]
    cfg_get_max_timeout: Callable[[web.Request], int]
    audit: Callable[[dict[str, Any]], None]
    emit_event: Callable[[str, dict | None], Any]
    now: Callable[[], float]

@dataclass(frozen=True)
class BatchHandlerContext:
    """Dependencies for batch operation handlers."""

    require_auth: Callable[[web.Request], web.Response | None]
    record_request: Callable[..., None]
    cors_json_response: Callable[..., web.Response]
    emit_event: Callable[[str, dict | None], Any]
    now: Callable[[], float]

@dataclass(frozen=True)
class AlertsHandlerContext:
    """Dependencies for alert configuration/status handlers."""

    require_auth: Callable[[web.Request], web.Response | None]
    record_request: Callable[..., None]
    cors_json_response: Callable[..., web.Response]
    metrics: dict[str, Any]
    watchdog_state: dict[str, Any]
    cdp_state: dict[str, Any]
    rate_limit_lock: Any
    rate_limit_store: dict[str, list[float]]
    rate_limit_window: float
    rate_limit_max: int
    now: Callable[[], float]
    log_info: Callable[..., None]


@dataclass(frozen=True)
class RateLimitHandlerContext:
    """Dependencies for rate-limit config/stat handlers."""

    require_auth: Callable[[web.Request], web.Response | None]
    record_request: Callable[..., None]
    cors_json_response: Callable[..., web.Response]
    update_rate_limit_config: Callable[[dict[str, Any]], None]
    rate_limit_stats: Callable[[], dict[str, Any]]
    log_info: Callable[..., None]

@dataclass(frozen=True)
class TlsHandlerContext:
    """Dependencies for TLS configuration handlers."""

    require_auth: Callable[[web.Request], web.Response | None]
    record_request: Callable[..., None]
    cors_json_response: Callable[..., web.Response]
    generate_self_signed_cert: Callable[[], tuple[str, str]]
    get_tailscale_cert: Callable[[], tuple[str, str]]
    log_info: Callable[..., None]

@dataclass(frozen=True)
class SandboxHandlerContext:
    """Dependencies for sandbox execution/configuration handlers."""

    require_auth: Callable[[web.Request], web.Response | None]
    record_request: Callable[..., None]
    cors_json_response: Callable[..., web.Response]
    blocked_reason: Callable[[str], str | None]
    first_word: Callable[[str], str]
    run_sandboxed: Callable[..., Any]
    audit: Callable[[dict[str, Any]], None]
    emit_event: Callable[[str, dict | None], Any]

@dataclass(frozen=True)
class ClusterHandlerContext:
    """Dependencies for cluster/high-availability handlers."""

    require_auth: Callable[[web.Request], web.Response | None]
    record_request: Callable[..., None]
    cors_json_response: Callable[..., web.Response]
    get_node_id: Callable[[], str]
    start_heartbeat: Callable[[], Any]
    stop_heartbeat: Callable[[], Any]
    audit: Callable[[dict[str, Any]], None]
    log_info: Callable[..., None]

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

@dataclass(frozen=True)
class GrpcHandlerContext:
    """Dependencies for gRPC-style secondary interface handlers."""

    require_auth: Callable[[web.Request], web.Response | None]
    record_request: Callable[..., None]
    cors_json_response: Callable[..., web.Response]
    server_task: Callable[[], Any]
    start_server: Callable[[dict[str, Any]], Any]
    stop_server: Callable[[], Any]

@dataclass(frozen=True)
class EventHandlerContext:
    """Dependencies for realtime event WebSocket handlers."""

    require_auth: Callable[[web.Request], web.Response | None]
    version: str
    utc_now: Callable[[], str]
    log_info: Callable[..., None]


@dataclass(frozen=True)
class WatchdogHandlerContext:
    """Dependencies for watchdog status/config handlers."""

    require_auth: Callable[[web.Request], web.Response | None]
    record_request: Callable[..., None]
    cors_json_response: Callable[..., web.Response]
    metrics: dict[str, Any]
    now: Callable[[], float]
    log_info: Callable[..., None]

@dataclass(frozen=True)
class GuiHandlerContext:
    """Dependencies for dashboard GUI handlers."""

    cors_json_response: Callable[..., web.Response]
    bridge_dir: Any
    version: str

