#!/usr/bin/env python3
"""
Arena Unified Bridge

Single asyncio-based process that multiplexes ALL services on one port (8765):
  - /health          GET   Public health check
  - /                GET   API index with endpoints list
  - /v1/version      GET   Version info
  - /v1/info         GET   Bridge info (auth required)
  - /v1/status       GET   Bridge status (auth required)
  - /v1/sysinfo      GET   Hardware/system info (auth required)
  - /v1/hwinfo       GET   Extended hardware info: mobo, BIOS, GPU, RAM modules, disks
  - /v1/inventory    GET   Full system inventory (runtimes, browsers, etc) via inventory.py
  - /v1/ps           GET   Active processes (auth required)
  - /v1/audit        GET   Audit log (auth required)
  - /v1/audit/stats  GET   Audit statistics (auth required)
  - /v1/exec         POST  Execute command (auth required)
  - /v1/kill         POST  Kill a running process (auth required)
  - /v1/upload       POST  Upload file (auth required)
  - /v1/download     GET   Download file (auth required)
  - /v1/memory       GET   List memory facts (auth required)
  - /v1/memory       POST  Set memory fact (auth required)
  - /v1/missions     GET   List missions (auth required)
  - /v1/mission/show GET   Show mission details (auth required)
  - /v1/beep         POST  Play sound notification (auth required)
  - /v1/doctor       GET   Run diagnostics (auth required)
  - /v1/reports      GET   List reports (auth required)
  - /v1/browser/search GET  Search DuckDuckGo (auth required)
  - /v1/browser/read GET   Readability-extract text (auth required)
  - /v1/browser/dump GET   Full page dump with links (auth required)
  - /v1/browser/fetch GET  Raw content fetch (auth required)
  - /v1/browser/head GET   HTTP HEAD request (auth required)
  - /v1/recall       GET   Smart memory recall with TF scoring (auth required)
  - /v1/recall/digest GET  Memory digest (auth required)
  - /v1/tasks        GET   List task queue (auth required)
  - /v1/tasks        POST  Submit task (auth required)
  - /v1/tasks/clean  POST  Clean completed tasks (auth required)
  - /v1/skills       GET   List skills (auth required)
  - /v1/skills/run   POST  Run a skill (auth required)
  - /v1/hooks        GET   List hooks (auth required)
  - /v1/agents       GET   List agent configs (auth required)
  - /v1/subagents    GET   List subagents (auth required)
  - /v1/subagents/spawn POST Spawn subagent (auth required)
  - /v1/sys/svc      GET   Service status (auth required)
  - /v1/sys/funnel   GET   Tailscale Funnel status (auth required)
  - /v1/token/regenerate POST  Generate new auth token (rewrites token.txt)
  - /v1/tailscale/funnel/{action} POST  start|stop|status
  - /v1/restart      POST  Graceful shutdown (auto-restart via task/systemd)
  - /v1/config       GET   Token-free configuration dump
  - /v1/metrics      GET   Bridge performance metrics
  - /v1/desktop/active_window GET  Get currently active window (v2.9.0)
  - /v1/desktop/focus POST  Focus window by id/title (v2.9.0)
  - /v1/control/status GET  Control lease status (v2.9.0)
  - /v1/control/pause POST Pause agent desktop control (v2.9.0)
  - /v1/control/resume POST Resume agent desktop control (v2.9.0)
  - /v1/control/revoke POST Revoke agent desktop control (v2.9.0)
  - /gui             GET   Dashboard HTML
  - /mcp             POST  MCP Streamable HTTP (JSON-RPC)
  - /mcp             DELETE Close MCP session
  - /sse             GET   MCP SSE legacy transport
  - /messages        POST  MCP SSE peer endpoint
  - /ws              WebSocket MCP transport
  - /run             POST  Web Gateway: run whitelisted command
  - /tool            POST  Web Gateway: proxy MCP tool call
  - /gateway         GET   Web Gateway info
  - /gateway/tools   GET   Web Gateway tools list

Security:
  - Binds to 127.0.0.1 by default (--bind to change)
  - Bearer token required for exec/info/status/audit/upload/download/kill
  - All commands logged to <bridge-dir>/audit.jsonl
  - Destructive patterns blocked (same as v0.4)
  - Profile-based allowlist (cautious / owner-shell)

Architecture:
  asyncio event loop + aiohttp.web for HTTP/WebSocket routing.
  Task runner integrated as asyncio background task (watches queue/inbox).
  Zero external dependencies beyond Python stdlib + aiohttp.
"""
from __future__ import annotations

import sys
import os
import sqlite3

# --- Windows pythonw.exe stdout/stderr fix ---
if sys.stdout is None:
    sys.stdout = open(os.devnull, "w")
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w")

# --- Windows resource module mock ---
if sys.platform == "win32":
    class MockResource:
        RLIMIT_NOFILE = 0
        def getrlimit(self, *a, **kw): return (1024, 1024)
        def setrlimit(self, *a, **kw): pass
    sys.modules["resource"] = MockResource()
    import resource  # noqa: E402

import argparse
import asyncio
import base64
import collections
import concurrent.futures
import hashlib
import hmac
import json
import multiprocessing
import platform
import re
import secrets
import shlex
import signal
import shutil
import socket
import subprocess
import tempfile
import threading
import time
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional
import urllib.request
from urllib.parse import parse_qs, urlparse

import aiohttp
from aiohttp import web

import logging
import logging.handlers
import traceback as _traceback

# ============================================================================
# VERSION & CONSTANTS
# ============================================================================
# Version, filesystem paths and tunable limits now live in arena/constants.py;
# re-exported here so existing references (`unified_bridge.VERSION`, `APP_DIR`, …)
# keep working.
from arena.constants import (  # noqa: E402,F401
    APP_DIR,
    AUDIT,
    AUDIT_CMD_LIMIT,
    BRIDGE_DIR,
    DEFAULT_MAX_CONCURRENT,
    DEFAULT_MAX_OUTPUT,
    MAX_BODY,
    TOKEN_FILE,
    VERSION,
)

# ============================================================================
# DESKTOP CONTROL STATE (v2.9.0)
# ============================================================================
# The control-lease state and helpers now live in arena/control.py; re-exported
# here so existing references (`unified_bridge._control_state`, etc.) keep working.
from arena.bootstrap import daemonize as _daemonize_runtime, ensure_session_env as _ensure_session_env_runtime, get_bridge_port as _get_bridge_port_runtime, load_config_file as _load_config_file_runtime, resolve_token as _resolve_token_runtime, setup_logging as _setup_logging_runtime  # noqa: E402,F401
from arena.errors import (  # noqa: E402,F401
    AuthError,
    BridgeError,
    BridgeTimeoutError,
    ErrorMiddlewareContext,
    ForbiddenError,
    NotFoundError,
    ResourceError,
    ValidationError,
    make_error_middleware,
)
from arena.control import (  # noqa: E402,F401
    _control_check,
    _control_lock,
    _control_record_agent_action,
    _control_state,
)


# Security primitives (command blocklist, desktop-input-injection guard, and
# SSRF URL validation) now live in arena/security.py. Re-exported here so
# existing references and tests (`unified_bridge.blocked_reason`, etc.) keep working.
from arena.security import (  # noqa: E402,F401
    BLOCK_PATTERNS,
    _INPUT_INJECTION_PATTERNS,
    _is_input_injection_cmd,
    _validate_url,
    blocked_reason,
)
from arena.rate_limit import (  # noqa: E402,F401
    _rate_limit_lock,
    _rate_limit_max,
    _rate_limit_store,
    _rate_limit_window,
    _rl_v2_config,
    _rl_v2_lock,
    _rl_v2_store,
    check_rate_limit as rl_check_rate_limit,
    check_rate_limit_v2 as rl_check_rate_limit_v2,
    rate_limit_stats,
    update_rate_limit_config,
)
from arena.auth.users import UserStore  # noqa: E402,F401
from arena.auth.runtime import AuthRuntimeContext, make_auth_runtime  # noqa: E402,F401
from arena.auth.handlers import make_user_handlers  # noqa: E402,F401
from arena.files.handlers import make_file_handlers  # noqa: E402,F401
from arena.exec.runner import (  # noqa: E402,F401
    ACTIVE_PROCESSES,
    active_processes_snapshot,
    run_shell_command,
)
from arena.exec.handlers import make_exec_handlers  # noqa: E402,F401
from arena.admin.compat import (  # noqa: E402,F401
    make_cloudflared_funnel_action_sync,
    make_sys_funnel_sync,
    make_tailscale_funnel_action_sync,
    make_token_path,
    make_token_regen_sync,
)
from arena.admin.runtime import (  # noqa: E402,F401
    CLOUDFLARED_STATE as _CLOUDFLARED_STATE,
    cloudflared_funnel_action as _cloudflared_funnel_action_runtime,
    sys_funnel_status as _sys_funnel_status_runtime,
    tailscale_funnel_action as _tailscale_funnel_action_runtime,
    token_regenerate as _token_regenerate_runtime,
)
from arena.admin.handlers import make_admin_handlers  # noqa: E402,F401
from arena.public.handlers import make_public_handlers  # noqa: E402,F401
from arena.gateway.runtime import GW_WHITELIST, gw_allowed, gw_run_sync as _gw_run_sync  # noqa: E402,F401
from arena.gateway.handlers import make_gateway_handlers  # noqa: E402,F401
from arena.mcp.runtime import (  # noqa: E402,F401
    MCP_SESSIONS,
    MCP_SESSION_MAX_AGE_MS,
    cleanup_mcp_sessions as _mcp_cleanup_sessions,
    now_ms,
    sid,
)
from arena.mcp.handlers import make_mcp_handlers  # noqa: E402,F401
from arena.mcp.tools import McpToolContext, make_mcp_tool_runtime  # noqa: E402,F401
from arena.events.runtime import EVENT_SUBSCRIBERS as _event_subscribers, emit_event as _events_emit_event  # noqa: E402,F401
from arena.events.handlers import make_event_handlers  # noqa: E402,F401
from arena.watchdog.runtime import (  # noqa: E402,F401
    WATCHDOG_STATE as _watchdog_state,
    start_watchdog as _watchdog_start,
    stop_watchdog as _watchdog_stop,
    watchdog_loop as _watchdog_loop,
)
from arena.watchdog.handlers import make_watchdog_handlers  # noqa: E402,F401
from arena.gui.handlers import (  # noqa: E402,F401
    DASHBOARD_V2_HTML as _DASHBOARD_V2_HTML,
    GUI_LOGIN_HTML as _GUI_LOGIN_HTML,
    make_gui_handlers,
)
from arena.grpc.runtime import (  # noqa: E402,F401
    GRPC_CONFIG as _grpc_config,
    grpc_handler as _grpc_handler,
    grpc_server_loop as _grpc_server_loop,
    grpc_server_task as _grpc_server_task,
    start_grpc_server,
    stop_grpc_server,
)
from arena.grpc.handlers import make_grpc_handlers  # noqa: E402,F401
from arena.profiles.handlers import (  # noqa: E402,F401
    PROFILES_DIR as _PROFILES_DIR,
    ensure_profiles_dir as _profiles_ensure_profiles_dir,
    make_profile_handlers,
)
from arena.cluster.runtime import (  # noqa: E402,F401
    CLUSTER_CONFIG as _cluster_config,
    CLUSTER_STATE as _cluster_state,
    cluster_heartbeat_loop as _cluster_runtime_heartbeat_loop,
    get_node_id as _cluster_get_node_id,
    start_cluster_heartbeat,
    stop_cluster_heartbeat,
)
from arena.cluster.handlers import make_cluster_handlers  # noqa: E402,F401
from arena.sandbox.runtime import SANDBOX_CONFIG as _sandbox_config, run_sandboxed as _sandbox_run_sandboxed  # noqa: E402,F401
from arena.sandbox.handlers import make_sandbox_handlers  # noqa: E402,F401
from arena.tls.handlers import (  # noqa: E402,F401
    TLS_CONFIG as _tls_config,
    generate_self_signed_cert as _tls_generate_self_signed_cert,
    get_tailscale_cert as _tls_get_tailscale_cert,
    make_tls_handlers,
)
from arena.batch.handlers import make_batch_handlers  # noqa: E402,F401
from arena.api_v2.handlers import (  # noqa: E402,F401
    DEPRECATED_ENDPOINTS as _DEPRECATED_ENDPOINTS,
    cfg_get_max_timeout,
    make_v2_handlers,
)


# Pure helper utilities now live in arena/util.py; re-exported for compatibility.
from arena.util import (  # noqa: E402,F401
    _NO_WINDOW_FLAG,
    _subprocess_kwargs,
    b64_token,
    decode_output,
    first_word,
    get_clean_platform_name,
    under_root,
    utc_now,
)

# Service/process/restart helpers extracted during v3 modularization.
from arena.service.runtime import (  # noqa: E402,F401
    _ps_utf8_command,
    _sc_query_running,
    _service_info_sync,
    _spawn_respawn_helper,
    _sys_svc_sync,
    _windows_bridge_processes,
    _windows_scheduled_task_info,
)

from arena.capabilities import build_capabilities  # noqa: E402,F401
from arena.inventory.hardware import (  # noqa: E402,F401
    hardware_from_inventory_result,
    merge_nvidia_gpu_facts,
    normalize_inventory_hardware,
)
from arena.inventory.runner import (  # noqa: E402,F401
    find_inventory_script,
    run_inventory,
)
from arena.tasks.queue import (  # noqa: E402,F401
    clean_tasks,
    list_tasks,
    submit_task,
)
from arena.tasks.runner import TaskRunnerContext, make_task_runner_runtime  # noqa: E402,F401
from arena.tasks.runtime import TaskQueueRuntimeContext, make_task_queue_runtime  # noqa: E402,F401
from arena.skills.registry import (  # noqa: E402,F401
    parse_skill_folder,
    scan_skills,
)
from arena.skills.cache import SkillsCache  # noqa: E402,F401
from arena.skills.install import (  # noqa: E402,F401
    install_skill,
    normalize_third_party_skill_name,
    uninstall_skill,
)
from arena.skills.runner import run_skill  # noqa: E402,F401
from arena.skills.runtime import SkillRuntimeContext, make_skill_runtime  # noqa: E402,F401
from arena.skills.handlers import make_skill_handlers  # noqa: E402,F401
from arena.desktop.runtime import (  # noqa: E402,F401
    _desktop_exec,
    _detect_desktop_env,
    _get_active_window,
    _kwin_windows_via_script,
)
from arena.desktop.screenshot import capture_desktop_screenshot  # noqa: E402,F401
from arena.desktop.focus import focus_window  # noqa: E402,F401
from arena.desktop.handlers import make_desktop_handlers  # noqa: E402,F401
from arena.control_handlers import make_control_lease_handlers  # noqa: E402,F401
from arena.browser.fetch import (  # noqa: E402,F401
    browser_dump,
    browser_fetch,
    browser_head,
    browser_read,
    browser_search,
)
from arena.browser.handlers import make_browser_browse_handlers, make_browser_fetch_handlers  # noqa: E402,F401
from arena.browser.runtime import BrowserRuntimeContext, make_browser_runtime  # noqa: E402,F401
from arena.browser.cdp.handlers import make_cdp_basic_handlers  # noqa: E402,F401
from arena.browser.cdp.diagnostics import make_cdp_diagnostic_handlers  # noqa: E402,F401
from arena.browser.cdp.session import make_cdp_session_handlers  # noqa: E402,F401
from arena.browser.cdp.page import make_cdp_page_handlers  # noqa: E402,F401
from arena.browser.cdp.tabs import make_cdp_tabs_handlers  # noqa: E402,F401
from arena.browser.cdp.cookies import ensure_cookie_manager as _cdp_ensure_cookie_manager, make_cdp_cookies_handlers  # noqa: E402,F401
from arena.browser.cdp.network import make_cdp_network_handlers  # noqa: E402,F401
from arena.browser.cdp.intercept import make_cdp_intercept_handlers  # noqa: E402,F401
from arena.browser.cdp.advanced import get_active_browser as _cdp_get_active_browser_from_context, make_cdp_advanced_handlers  # noqa: E402,F401
from arena.browser.cdp.runtime import (  # noqa: E402,F401
    _cdp_connect_lock,
    _cdp_state,
    _get_cdp_module,
    _start_cdp_watcher,
    _stop_cdp_watcher,
    cdp_watcher_active as _cdp_watcher_active,
)
from arena.browser.cdp.active_tab import cdp_active_tab as _cdp_active_tab_impl  # noqa: E402,F401
from arena.resources.listing import (  # noqa: E402,F401
    list_agents,
    list_hooks,
    list_missions,
    list_reports,
    list_subagents,
    show_mission,
)
from arena.resources.handlers import make_resource_handlers  # noqa: E402,F401
from arena.resources.runtime import ResourceRuntimeContext, make_resource_runtime  # noqa: E402,F401
from arena.resources.subagents import spawn_subagent  # noqa: E402,F401
from arena.memory.handlers import make_memory_handlers  # noqa: E402,F401
from arena.memory.runtime import MemoryRuntimeContext, make_memory_runtime  # noqa: E402,F401
from arena.memory.store import (  # noqa: E402,F401
    delete_fact as memory_delete_fact,
    init_memory_db as memory_init_db,
    load_facts as memory_load_facts,
    recall as memory_recall,
    recall_digest as memory_recall_digest,
    search_facts_paged as memory_search_facts_paged,
    write_fact as memory_write_fact,
)
from arena.desktop.input import (  # noqa: E402,F401
    build_click_command,
    build_key_command,
    build_mouse_command,
    build_type_command,
)
from arena.http import (  # noqa: E402,F401
    CORS_HEADERS,
    _cors_json_response,
    cors_json_response,
)
from arena.observability.metrics import (  # noqa: E402,F401
    BRIDGE_METRICS,
    _metrics_lock,
    _record_request,
    record_request,
)
from arena.observability.audit import (  # noqa: E402,F401
    audit_lock,
    audit_stats,
    read_tail as audit_read_tail,
    sanitize_audit_event as audit_sanitize_event,
    write_audit_event,
)
from arena.observability.request_log import (  # noqa: E402,F401
    log_request_response as request_log_response,
    read_request_log,
    request_log_lock,
)
from arena.observability.webhooks import (  # noqa: E402,F401
    fire_webhooks,
    load_webhooks,
    normalize_webhooks_config,
    save_webhooks,
)
from arena.observability.handlers import make_observability_handlers  # noqa: E402,F401
from arena.observability.runtime_handlers import make_runtime_observability_handlers  # noqa: E402,F401
from arena.observability.audit_runtime import AuditRuntimeContext, make_audit_runtime  # noqa: E402,F401
from arena.observability.log_cleanup import LogCleanupContext, make_log_cleanup_runtime  # noqa: E402,F401
from arena.observability.alerts import ALERTS_CONFIG as _ALERTS_CONFIG, make_alert_handlers  # noqa: E402,F401
from arena.observability.ratelimit_handlers import make_rate_limit_handlers  # noqa: E402,F401
from arena.observability.tracing import (  # noqa: E402,F401
    _otel_config,
    _otel_lock,
    _otel_record_span,
    _otel_should_sample,
    _otel_trace_id,
    _otel_traces,
    make_tracing_handlers,
)
from arena.system.handlers import make_system_handlers  # noqa: E402,F401
from arena.system.sysinfo import (  # noqa: E402,F401
    collect_sysinfo,
    sysinfo_cim_cpu_counts,
)
from arena.system.doctor import (  # noqa: E402,F401
    check_internet,
    run_doctor,
)
from arena.system.sound import (  # noqa: E402,F401
    generate_wav_bytes,
    linux_play_beep,
    play_beep,
    winsound_melody,
)
from arena.system.hwinfo_legacy import collect_legacy_hwinfo  # noqa: E402,F401
from arena.system.inventory_compat import (  # noqa: E402,F401
    make_hardware_from_inventory_sync,
    make_hwinfo_sync,
    make_inventory_sync,
)
from arena.system.compat import (  # noqa: E402,F401
    make_check_internet_sync,
    make_common_status,
    make_doctor_sync,
    make_play_beep_sync,
    make_sysinfo_cim_sync,
    make_sysinfo_sync,
)
from arena.handler_context import HandlerContext, ServiceHandlerContext, TaskHandlerContext, SkillHandlerContext, DesktopHandlerContext, ControlLeaseHandlerContext, BrowserFetchHandlerContext, BrowserBrowseHandlerContext, CdpBasicHandlerContext, CdpDiagnosticHandlerContext, CdpSessionHandlerContext, CdpPageHandlerContext, CdpTabsHandlerContext, CdpCookiesHandlerContext, CdpNetworkHandlerContext, CdpInterceptHandlerContext, CdpAdvancedHandlerContext, ResourceHandlerContext, MemoryHandlerContext, ObservabilityHandlerContext, SystemHandlerContext, UserHandlerContext, FileHandlerContext, ExecHandlerContext, GatewayHandlerContext, TracingHandlerContext, ApiV2HandlerContext, BatchHandlerContext, AlertsHandlerContext, RateLimitHandlerContext, TlsHandlerContext, SandboxHandlerContext, ClusterHandlerContext, ProfileHandlerContext, GrpcHandlerContext, EventHandlerContext, WatchdogHandlerContext, GuiHandlerContext, McpHandlerContext, RuntimeObservabilityHandlerContext, PublicHandlerContext, AdminHandlerContext  # noqa: E402,F401
from arena.inventory.handlers import make_hardware_handlers  # noqa: E402,F401
from arena.service.capabilities import make_capabilities_sync  # noqa: E402,F401
from arena.service.handlers import make_service_handlers  # noqa: E402,F401
from arena.tasks.handlers import make_task_handlers  # noqa: E402,F401
from arena.routes import register_routes  # noqa: E402,F401
from arena.app import make_app as _make_arena_app  # noqa: E402,F401
from arena.container import AdminWiringContext, PublicWiringContext, ServiceWiringContext, SystemWiringContext, build_admin_handlers, build_container, build_context_handlers, build_public_handlers, build_service_handlers, build_system_handlers, export_handler_attrs  # noqa: E402,F401
from arena.wiring.legacy_registries import build_early_handler_registries  # noqa: E402,F401
from arena.wiring.legacy_system import build_system_public_admin_registries  # noqa: E402,F401
from arena.wiring.legacy_hardware_exec import build_hardware_exec_registries  # noqa: E402,F401
from arena.wiring.legacy_runtimes import build_memory_resource_browser_runtimes  # noqa: E402,F401
from arena.wiring.legacy_service_browser import build_service_browser_registries  # noqa: E402,F401
from arena.wiring.legacy_cdp import build_cdp_registries  # noqa: E402,F401
from arena.wiring.legacy_desktop import build_desktop_registries  # noqa: E402,F401
from arena.wiring.legacy_memory_observability import build_memory_observability_registries  # noqa: E402,F401
from arena.wiring.legacy_tasks_skills_resources import build_tasks_skills_resources_registries  # noqa: E402,F401
from arena.wiring.legacy_mcp_task import build_mcp_task_runtimes  # noqa: E402,F401
from arena.wiring.legacy_observability_runtime import build_observability_runtimes  # noqa: E402,F401
from arena.wiring.legacy_lifecycle import build_app_lifecycle  # noqa: E402,F401
from arena.paths import ArenaPaths  # noqa: E402,F401
from arena.lifecycle import LifecycleContext, make_lifecycle  # noqa: E402,F401
from arena.cli import CliContext, main as _cli_main, serve as _cli_serve, token_cmd as _cli_token_cmd  # noqa: E402,F401


def _ensure_session_env() -> None:
    return _ensure_session_env_runtime()


def _load_config_file() -> dict:
    return _load_config_file_runtime(
        log_info=log.info,
        log_debug=log.debug,
        log_warning=log.warning,
    )


def _get_bridge_port() -> int:
    return _get_bridge_port_runtime()


# Version, paths and limits now live in arena/constants.py (re-exported near the
# top of this file). Runtime state stays here.

# ============================================================================
# STRUCTURED LOGGING
# ============================================================================

LOG_FILE = APP_DIR / "bridge.log"


def _setup_logging() -> logging.Logger:
    return _setup_logging_runtime(app_dir=APP_DIR, log_file=LOG_FILE)


log = _setup_logging()


# ============================================================================
# ERROR MIDDLEWARE / STRUCTURED EXCEPTIONS
# ============================================================================
# Structured bridge exceptions and middleware factory now live in arena/errors.py.


# Thread pool executor for running blocking I/O in async handlers
_EXECUTOR = concurrent.futures.ThreadPoolExecutor(max_workers=8, thread_name_prefix="bridge_io")
# Dedicated executor for potentially slow operations (hwinfo)
# to avoid blocking the main executor pool
_SLOW_EXECUTOR = concurrent.futures.ThreadPoolExecutor(max_workers=2, thread_name_prefix="bridge_slow")

# ============================================================================
# CDP (Chrome DevTools Protocol) runtime
# ============================================================================
# CDP state, lazy module loading and watcher tasks now live in
# arena/browser/cdp/runtime.py. Imported above to preserve historical globals.

# ============================================================================
# BRIDGE METRICS (request counter tracking)
# ============================================================================
# BRIDGE_METRICS, _metrics_lock and _record_request now live in
# arena/observability/metrics.py and are imported near the top of this file.

# Global reference to the aiohttp Application (set in make_app)
_app_ref: Any = None

# Rate limit state/checks now live in arena/rate_limit.py.

# ============================================================================
# PHASE 3: WebSocket Real-Time Events
# ============================================================================
# Realtime event stream runtime/handler now live in arena/events/. The wrapper
# below preserves the historical `emit_event(event_type, data)` helper.


async def emit_event(event_type: str, data: dict | None = None) -> None:
    return await _events_emit_event(event_type, data, utc_now_fn=utc_now)


# ============================================================================
# PHASE 3: Plugin/Hot-Reload System for Skills
# ============================================================================
_skills_cache_obj: SkillsCache | None = None


def _get_skills_cache() -> SkillsCache:
    global _skills_cache_obj
    if _skills_cache_obj is None:
        _skills_cache_obj = SkillsCache(skills_dir=SKILLS_DIR, scan_fn=_skills_list_sync, ttl=5.0, hot_reload=True)
    return _skills_cache_obj


def _skills_list_sync_with_cache() -> dict:
    """Scan skills with caching and hot-reload support."""
    return _get_skills_cache().list()


def _skills_cache_reset() -> None:
    """Reset cached skills so the next list call rescans the filesystem."""
    _get_skills_cache().reset()




# ============================================================================
# PHASE 3: Request/Response Logging
# ============================================================================
_REQ_LOG_FILE = APP_DIR / "requests.jsonl"
_REQ_LOG_MAX_BYTES = 10 * 1024 * 1024  # 10MB before rotation
_REQ_LOG_BACKUP_COUNT = 3


def _log_request_response(method: str, path: str, status: int, duration: float,
                           req_id: str, peer: str = "", error: str = "") -> None:
    """Log request/response to requests.jsonl for observability."""
    return request_log_response(
        log_file=_REQ_LOG_FILE,
        app_dir=APP_DIR,
        utc_now_fn=utc_now,
        method=method,
        path=path,
        status=status,
        duration=duration,
        req_id=req_id,
        peer=peer,
        error=error,
        lock=request_log_lock,
        max_bytes=_REQ_LOG_MAX_BYTES,
        backup_count=_REQ_LOG_BACKUP_COUNT,
    )




# ============================================================================
# PHASE 3: Health Watchdog (auto-restart, memory/CPU monitoring, alerts)
# ============================================================================
# Watchdog runtime and handler now live in arena/watchdog/. Wrappers preserve
# historical helper names used by startup/cleanup code.


def _start_watchdog() -> None:
    _watchdog_start(
        utc_now_fn=utc_now,
        emit_event_fn=emit_event,
        log_info=log.info,
        log_warning=log.warning,
        log_error=log.error,
    )


def _stop_watchdog() -> None:
    _watchdog_stop(log_info=log.info)


# ============================================================================
# PHASE 3: Multi-User Auth with Roles
# ============================================================================
# User store lives in arena/auth/users.py; auth runtime helpers live in
# arena/auth/runtime.py. Bind compatibility globals here.
_USERS_FILE = APP_DIR / "users.json"
_user_store = UserStore(_USERS_FILE, log_warning=log.warning, log_debug=log.debug)
_auth_runtime_ctx = AuthRuntimeContext(
    user_store=_user_store,
    rate_limit_lock=_rate_limit_lock,
    rate_limit_store=_rate_limit_store,
    cors_json_response=_cors_json_response,
    log_warning=log.warning,
    now=time.time,
)
_auth_runtime = make_auth_runtime(_auth_runtime_ctx)
_load_users = _auth_runtime.load_users
check_auth_with_role = _auth_runtime.check_auth_with_role


# ============================================================================
# PHASE 3: Batch Operations API
# ============================================================================
# Batch operation handler now lives in arena/batch/handlers.py; bound below via
# make_batch_handlers(...) to preserve the public route global.


# ============================================================================
# PHASE 3: Browser Session Profiles
# ============================================================================
# Browser session profile handlers now live in arena/profiles/handlers.py.
# The wrapper preserves the historical `_ensure_profiles_dir()` helper name.


def _ensure_profiles_dir() -> Path:
    return _profiles_ensure_profiles_dir()


# ============================================================================
# PHASE 3: Prometheus Alerts Configuration
# ============================================================================
# Alert configuration/status handler now lives in arena/observability/alerts.py;
# imported above and re-exported here for compatibility.


# ============================================================================
# PHASE 4: Built-in TLS/HTTPS Support
# ============================================================================
# TLS config/runtime helpers and handler now live in arena/tls/handlers.py;
# imported above and re-exported here for compatibility.


def _generate_self_signed_cert() -> tuple[str, str]:
    return _tls_generate_self_signed_cert(log_info=log.info, log_warning=log.warning)


def _get_tailscale_cert() -> tuple[str, str]:
    return _tls_get_tailscale_cert(log_info=log.info)


# ============================================================================
# PHASE 4: gRPC-style Secondary Interface
# ============================================================================
# gRPC-style secondary interface runtime and management handler now live in
# arena/grpc/. Imported above and re-exported here for compatibility.


# ============================================================================
# PHASE 4: Live Dashboard v2
# ============================================================================
# Dashboard v2 HTML/template handler now lives in arena/gui/handlers.py.


# ============================================================================
# PHASE 4: Rate Limiting v2 (per-user, per-endpoint with X-RateLimit-* headers)
# ============================================================================
# Enhanced rate limit state lives in arena/rate_limit.py.


def _check_rate_limit_v2(request: web.Request) -> web.Response | None:
    return rl_check_rate_limit_v2(
        request,
        check_auth_with_role_fn=check_auth_with_role,
        cors_json_response_fn=_cors_json_response,
    )


# Rate-limit configuration/stat handler now lives in
# arena/observability/ratelimit_handlers.py; bound below via
# make_rate_limit_handlers(...) to preserve the public route global.


# ============================================================================
# PHASE 4: Skill Sandboxing (isolated execution with resource limits)
# ============================================================================
# Sandbox runtime/config and handler now live in arena/sandbox/. The wrapper
# below preserves the historical `_run_sandboxed(...)` helper signature used by
# v2 compatibility code and tests.


async def _run_sandboxed(cmd: str, timeout: int = 30, memory_mb: int = 256) -> dict:
    return await _sandbox_run_sandboxed(
        cmd,
        timeout=timeout,
        memory_mb=memory_mb,
        root_agent=ROOT_AGENT,
        decode_output_fn=decode_output,
    )


# ============================================================================
# PHASE 4: Clustering / High Availability
# ============================================================================
# Cluster runtime state/helpers and route handler now live in arena/cluster/.
# Wrappers below preserve historical helper names for compatibility.


def _get_node_id() -> str:
    return _cluster_get_node_id()


async def _cluster_heartbeat_loop() -> None:
    await _cluster_runtime_heartbeat_loop(log_error=log.error)


# ============================================================================
# PHASE 4: API Versioning (/v2/ endpoints with deprecation headers)
# ============================================================================
# v2 compatibility API handlers and deprecation metadata now live in
# arena/api_v2/handlers.py; imported above and re-exported here for middleware
# and route compatibility.


# ============================================================================
# PHASE 4: OpenTelemetry Tracing
# ============================================================================
# OpenTelemetry-style tracing state/helpers and route handlers now live in
# arena/observability/tracing.py; imported above and re-exported here for
# compatibility with existing middleware/metrics references.



def _check_rate_limit(request: web.Request) -> web.Response | None:
    return rl_check_rate_limit(request, cors_json_response_fn=_cors_json_response)

CAUTIOUS_ALLOW = {
    "echo", "pwd", "ls", "dir", "tree", "find", "fd", "rg", "grep", "cat", "type",
    "head", "tail", "wc", "whoami", "hostname", "uname", "ver", "systeminfo",
    "ipconfig", "ifconfig", "ip", "ss", "netstat", "python", "python3", "py",
    "node", "npm", "pnpm", "yarn", "bun", "deno", "uv", "git", "gh", "go",
    "cargo", "rustc", "java", "javac", "mvn", "gradle", "dotnet", "pacman",
    "paru", "yay", "winget", "choco", "scoop", "pip", "pip3", "bash", "sh",
    "zsh", "fish", "pwsh", "powershell", "cmd", "agentctl",
}

# BLOCK_PATTERNS and blocked_reason now live in arena/security.py (re-exported above).

HOME = str(Path.home())
BIN = str(BRIDGE_DIR / "bin")

# ============================================================================
# HELPERS
# ============================================================================

# utc_now, get_clean_platform_name, decode_output, b64_token, first_word and
# under_root now live in arena/util.py (re-exported near the top of this file).







# ============================================================================
# AUDIT
# ============================================================================
# Audit/webhook runtime wrappers live in arena/observability/audit_runtime.py.

_observability_runtime_registry = build_observability_runtimes(globals())
globals().update(_observability_runtime_registry)


# ============================================================================
# MCP SSE SESSIONS
# ============================================================================
# MCP session state/helpers now live in arena/mcp/runtime.py.


PATHS = ArenaPaths.from_env(BRIDGE_DIR)
ROOT_AGENT = PATHS.root_agent
QUEUE = PATHS.queue
INBOX = PATHS.inbox
RUNNING = PATHS.running
DONE = PATHS.done
FAILED = PATHS.failed

# Additional directory constants for new endpoints
SKILLS_DIR = PATHS.skills_dir
HOOKS_DIR = PATHS.hooks_dir
AGENTS_DIR = PATHS.agents_dir
SUBAGENTS_DIR = PATHS.subagents_dir
MEMORY_FILE = PATHS.memory_file
MEMORY_DB = PATHS.memory_db
MISSIONS_DIR = PATHS.missions_dir
REPORTS_DIR = PATHS.reports_dir
WEBHOOKS_FILE = PATHS.webhooks_file
# BACKUPS_DIR removed in v2.5.2 — backup feature deleted

_mcp_task_runtime_registry = build_mcp_task_runtimes(globals())
globals().update(_mcp_task_runtime_registry)


# ============================================================================
# APP CONFIG
# ============================================================================

_shutdown_event: asyncio.Event | None = None
_app_lifecycle_registry = build_app_lifecycle(globals())
globals().update(_app_lifecycle_registry)


# ============================================================================
# AUTH HELPER
# ============================================================================
# check_auth/require_auth implementations live in arena/auth/runtime.py.
check_auth = _auth_runtime.check_auth
require_auth = _auth_runtime.require_auth


_early_handler_registry = build_early_handler_registries(globals())
globals().update(_early_handler_registry)

_check_internet_sync = make_check_internet_sync(check_internet)
_doctor_sync = make_doctor_sync(
    run_doctor_fn=run_doctor,
    version=VERSION,
    bridge_dir=BRIDGE_DIR,
    memory_dir=MEMORY_FILE.parent,
    missions_dir=MISSIONS_DIR,
    facts_count_fn=lambda: len(_load_facts()),
    internet_check_fn=_check_internet_sync,
    home_dir=Path.home(),
)
_play_beep_sync = make_play_beep_sync(
    play_beep_fn=play_beep,
    subprocess_kwargs_fn=_subprocess_kwargs,
)
_sysinfo_cim_sync = make_sysinfo_cim_sync(
    sysinfo_cim_cpu_counts_fn=sysinfo_cim_cpu_counts,
    subprocess_kwargs_fn=_subprocess_kwargs,
)
_sysinfo_sync = make_sysinfo_sync(
    collect_sysinfo_fn=collect_sysinfo,
    clean_platform_name_fn=get_clean_platform_name,
    subprocess_kwargs_fn=_subprocess_kwargs,
)
common_status = make_common_status(
    version=VERSION,
    audit_path=AUDIT,
    clean_platform_name_fn=get_clean_platform_name,
)
_system_public_admin_registry = build_system_public_admin_registries(globals())
globals().update(_system_public_admin_registry)


# ============================================================================
# HANDLERS — Public
# ============================================================================
# Public index and health handlers now live in arena/public/handlers.py.



_hwinfo_sync = make_hwinfo_sync(
    collect_legacy_hwinfo_fn=collect_legacy_hwinfo,
    subprocess_kwargs_fn=_subprocess_kwargs,
)
_inventory_sync = make_inventory_sync(
    run_inventory_fn=run_inventory,
    bridge_dir=BRIDGE_DIR,
    root_agent=ROOT_AGENT,
    python_executable=sys.executable or "python3",
)
_hardware_from_inventory_sync = make_hardware_from_inventory_sync(
    globals_ref=globals(),
    hardware_from_inventory_result_fn=hardware_from_inventory_result,
)
_hardware_exec_registry = build_hardware_exec_registries(globals())
globals().update(_hardware_exec_registry)























# ============================================================================
# HANDLER — Dashboard GUI
# ============================================================================
# Dashboard GUI templates/handlers now live in arena/gui/handlers.py.


# ============================================================================
# HANDLERS — Dashboard API endpoints
# ============================================================================

_memory_resource_browser_runtime_registry = build_memory_resource_browser_runtimes(globals())
globals().update(_memory_resource_browser_runtime_registry)


# ============================================================================
# HANDLERS — v1.5.0 New Endpoints
# ============================================================================

# --- /v1/service/info GET — What manages this bridge process? ---














# --- /v1/sys/svc GET — Service status ---





_capabilities_sync = make_capabilities_sync(
    build_capabilities_fn=build_capabilities,
    version=VERSION,
    get_cdp_module=_get_cdp_module,
    cdp_state=_cdp_state,
    detect_desktop_env=_detect_desktop_env,
    service_info_sync=_service_info_sync,
    sys_svc_sync=_sys_svc_sync,
)
_sys_funnel_sync = make_sys_funnel_sync(
    sys_funnel_status_fn=_sys_funnel_status_runtime,
    subprocess_kwargs_fn=_subprocess_kwargs,
)
_token_path = make_token_path(default_token_file=TOKEN_FILE)
_token_regen_sync = make_token_regen_sync(
    token_regenerate_fn=_token_regenerate_runtime,
    default_token_file=TOKEN_FILE,
)
_tailscale_funnel_action_sync = make_tailscale_funnel_action_sync(
    tailscale_funnel_action_fn=_tailscale_funnel_action_runtime,
)
_cloudflared_funnel_action_sync = make_cloudflared_funnel_action_sync(
    cloudflared_funnel_action_fn=_cloudflared_funnel_action_runtime,
    root_agent=ROOT_AGENT,
    subprocess_kwargs_fn=_subprocess_kwargs,
)
_service_browser_registry = build_service_browser_registries(globals())
globals().update(_service_browser_registry)


_cdp_registry = build_cdp_registries(globals())
globals().update(_cdp_registry)
_desktop_registry = build_desktop_registries(globals())
globals().update(_desktop_registry)


# Memory recall helpers moved to arena/memory/runtime.py and bound above.


_memory_observability_registry = build_memory_observability_registries(globals())
globals().update(_memory_observability_registry)
_tasks_skills_resources_registry = build_tasks_skills_resources_registries(globals())
globals().update(_tasks_skills_resources_registry)


# --- /v1/browser/browse POST — Unified browser endpoint with auto CDP/BrowserAct switching ---
# Handler now lives in arena/browser/handlers.py and is bound above via
# make_browser_browse_handlers(...) to preserve the public route global.


# --- /v1/metrics and /metrics — Runtime metrics ---
# Runtime metrics and Prometheus handlers now live in
# arena/observability/runtime_handlers.py. Bound below via
# make_runtime_observability_handlers(...) to preserve route globals.


# --- /api-docs GET — OpenAPI 3.0 specification ---
# OpenAPI docs handler now lives in arena/public/handlers.py.


# ============================================================================
# HANDLERS — MCP Streamable HTTP / SSE / WebSocket
# ============================================================================
# MCP transport handlers now live in arena/mcp/handlers.py and are bound below
# via make_mcp_handlers(...) to preserve public route globals.


# ============================================================================
# HANDLERS — Web Gateway
# ============================================================================
# Gateway handlers now live in arena/gateway/handlers.py. Bound above via
# make_gateway_handlers(...) to preserve public route globals.


# ============================================================================
# MAIN
# ============================================================================

def resolve_token(cli_token: str | None) -> tuple[str, Path]:
    return _resolve_token_runtime(
        cli_token,
        default_token_file=TOKEN_FILE,
        token_generator=b64_token,
        log_info=log.info,
    )


def _daemonize() -> None:
    return _daemonize_runtime(log_error=log.error)


def _set_rate_limit_config_from_file(rl: dict[str, Any]) -> None:
    global _rate_limit_max, _rate_limit_window
    if rl.get("max_requests"):
        _rate_limit_max = int(rl["max_requests"])
    if rl.get("window_seconds"):
        _rate_limit_window = float(rl["window_seconds"])


_cli_ctx = CliContext(
    version=VERSION,
    audit_path=AUDIT,
    default_max_output=DEFAULT_MAX_OUTPUT,
    default_max_concurrent=DEFAULT_MAX_CONCURRENT,
    cdp_state=_cdp_state,
    make_app=make_app,
    resolve_token=resolve_token,
    token_generator=b64_token,
    daemonize=_daemonize,
    ensure_session_env=_ensure_session_env,
    load_config_file=_load_config_file,
    rotate_all_logs_on_startup=_rotate_all_logs_on_startup,
    signal_handler=_signal_handler,
    set_rate_limit_config=_set_rate_limit_config_from_file,
    log_info=log.info,
)


def serve(args: argparse.Namespace) -> None:
    return _cli_serve(args, _cli_ctx)


def token_cmd(args: argparse.Namespace) -> None:
    return _cli_token_cmd(args, _cli_ctx)


def main() -> None:
    return _cli_main(_cli_ctx)


if __name__ == "__main__":
    main()
