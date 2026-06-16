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
from arena.handler_context import HandlerContext, ServiceHandlerContext, TaskHandlerContext, SkillHandlerContext, DesktopHandlerContext, ControlLeaseHandlerContext, BrowserFetchHandlerContext, BrowserBrowseHandlerContext, CdpBasicHandlerContext, CdpDiagnosticHandlerContext, CdpSessionHandlerContext, CdpPageHandlerContext, CdpTabsHandlerContext, CdpCookiesHandlerContext, CdpNetworkHandlerContext, CdpInterceptHandlerContext, CdpAdvancedHandlerContext, ResourceHandlerContext, MemoryHandlerContext, ObservabilityHandlerContext, SystemHandlerContext, UserHandlerContext, FileHandlerContext, ExecHandlerContext, GatewayHandlerContext, TracingHandlerContext, ApiV2HandlerContext, BatchHandlerContext, AlertsHandlerContext, RateLimitHandlerContext, TlsHandlerContext, SandboxHandlerContext, ClusterHandlerContext, ProfileHandlerContext, GrpcHandlerContext, EventHandlerContext, WatchdogHandlerContext, GuiHandlerContext, McpHandlerContext, RuntimeObservabilityHandlerContext, PublicHandlerContext, AdminHandlerContext  # noqa: E402,F401
from arena.inventory.handlers import make_hardware_handlers  # noqa: E402,F401
from arena.service.handlers import make_service_handlers  # noqa: E402,F401
from arena.tasks.handlers import make_task_handlers  # noqa: E402,F401
from arena.routes import register_routes  # noqa: E402,F401
from arena.app import make_app as _make_arena_app  # noqa: E402,F401
from arena.container import AdminWiringContext, PublicWiringContext, ServiceWiringContext, SystemWiringContext, build_admin_handlers, build_container, build_context_handlers, build_public_handlers, build_service_handlers, build_system_handlers, export_handler_attrs  # noqa: E402,F401
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

_audit_runtime_ctx = AuditRuntimeContext(
    audit_path=AUDIT,
    app_dir=APP_DIR,
    webhooks_file=Path(os.environ.get("ARENA_AGENT_HOME", str(BRIDGE_DIR))).expanduser() / "webhooks.json",
    utc_now=utc_now,
    slow_executor=_SLOW_EXECUTOR,
    log_debug=log.debug,
)
_audit_runtime = make_audit_runtime(_audit_runtime_ctx)
sanitize_audit_event = _audit_runtime.sanitize_audit_event
_load_webhooks = _audit_runtime.load_webhooks
_save_webhooks = _audit_runtime.save_webhooks
_fire_webhooks = _audit_runtime.fire_webhooks
audit = _audit_runtime.audit
read_tail = _audit_runtime.read_tail


_error_middleware_ctx = ErrorMiddlewareContext(
    check_rate_limit_v2=_check_rate_limit_v2,
    check_rate_limit=_check_rate_limit,
    record_request=_record_request,
    log_request_response=_log_request_response,
    cors_json_response=_cors_json_response,
    audit=audit,
    log_debug=log.debug,
    log_warning=log.warning,
    log_error=log.error,
)
error_middleware = make_error_middleware(_error_middleware_ctx)


# ============================================================================
# LOG ROTATION & DISK SAFETY (v2.1.0 — prevents disk fill)
# ============================================================================
# Runtime implementation lives in arena/observability/log_cleanup.py.

_MAX_LOG_SIZE = 10 * 1024 * 1024
_MAX_LOG_BACKUPS = 3
_LOG_FILES_TO_ROTATE = [
    APP_DIR / "bridge.log",
    APP_DIR / "requests.jsonl",
    APP_DIR / "audit.jsonl",
]
_log_cleanup_ctx = LogCleanupContext(
    app_dir=APP_DIR,
    log_files=_LOG_FILES_TO_ROTATE,
    max_log_size=_MAX_LOG_SIZE,
    max_log_backups=_MAX_LOG_BACKUPS,
    log_info=log.info,
    log_warning=log.warning,
    log_critical=log.critical,
    log_error=log.error,
)
_log_cleanup_runtime = make_log_cleanup_runtime(_log_cleanup_ctx)
_rotate_file_if_oversized = _log_cleanup_runtime.rotate_file_if_oversized
_rotate_all_logs_on_startup = _log_cleanup_runtime.rotate_all_logs_on_startup
_check_disk_space = _log_cleanup_runtime.check_disk_space
_log_cleanup_loop = _log_cleanup_runtime.log_cleanup_loop


# ============================================================================
# MCP SSE SESSIONS
# ============================================================================
# MCP session state/helpers now live in arena/mcp/runtime.py.


def _cleanup_mcp_sessions() -> int:
    return _mcp_cleanup_sessions(MCP_SESSIONS)


# ============================================================================
# WEB GATEWAY WHITELIST
# ============================================================================
# Web Gateway whitelist/runtime helpers now live in arena/gateway/runtime.py;
# imported above and re-exported here for compatibility.

# ============================================================================
# TASK RUNNER (integrated asyncio background)
# ============================================================================

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


# ============================================================================
# MCP TOOLS REGISTRY / JSON-RPC dispatcher
# ============================================================================
# MCP tool registry and JSON-RPC dispatch now live in arena/mcp/tools.py.


def _mcp_app_config() -> dict:
    return _app_ref.get("cfg", {}) if _app_ref else {}


_mcp_tool_ctx = McpToolContext(
    version=VERSION,
    bin_dir=BIN,
    bridge_dir=BRIDGE_DIR,
    reports_dir=REPORTS_DIR,
    subprocess_kwargs=_subprocess_kwargs,
    blocked_reason=blocked_reason,
    first_word=first_word,
    cautious_allow=CAUTIOUS_ALLOW,
    under_root=under_root,
    write_fact=lambda entry: _write_fact(entry),
    load_facts=lambda: _load_facts(),
    audit=audit,
    app_config=_mcp_app_config,
    common_status=lambda cfg: common_status(cfg),
    skills_list_sync_with_cache=_skills_list_sync_with_cache,
    skills_run_sync=lambda *args, **kwargs: _skills_run_sync(*args, **kwargs),
)
_mcp_tool_runtime = make_mcp_tool_runtime(_mcp_tool_ctx)
MCP_TOOLS = _mcp_tool_runtime.tools
run_local = _mcp_tool_runtime.run_local
run_sd = _mcp_tool_runtime.run_sd
text_content = _mcp_tool_runtime.text_content
call_tool = _mcp_tool_runtime.call_tool
handle_rpc = _mcp_tool_runtime.handle_rpc




_task_runner_ctx = TaskRunnerContext(
    inbox=INBOX,
    running=RUNNING,
    done=DONE,
    failed=FAILED,
    blocked_reason=blocked_reason,
    cleanup_mcp_sessions=_cleanup_mcp_sessions,
    utc_now=utc_now,
    log_info=log.info,
    log_error=log.error,
)
_task_runner_runtime = make_task_runner_runtime(_task_runner_ctx)
move_atomic = _task_runner_runtime.move_atomic
task_ensure_dirs = _task_runner_runtime.ensure_dirs
task_run_one = _task_runner_runtime.run_one
task_runner_loop = _task_runner_runtime.runner_loop


# ============================================================================
# APP CONFIG
# ============================================================================

def _set_app_ref(app: web.Application) -> None:
    global _app_ref
    _app_ref = app


def make_app(cfg: dict) -> web.Application:
    container = build_container(globals())
    return _make_arena_app(
        cfg,
        handlers=container.handlers,
        error_middleware=error_middleware,
        on_startup=on_startup,
        on_cleanup=on_cleanup,
        set_app_ref=_set_app_ref,
    )


def _get_shutdown_event() -> asyncio.Event | None:
    return _shutdown_event


_lifecycle_ctx = LifecycleContext(
    executor=_EXECUTOR,
    slow_executor=_SLOW_EXECUTOR,
    init_memory_db=lambda: init_memory_db(),
    task_runner_loop=task_runner_loop,
    log_cleanup_loop=_log_cleanup_loop,
    start_watchdog=_start_watchdog,
    stop_watchdog=_stop_watchdog,
    stop_cdp_watcher=_stop_cdp_watcher,
    cdp_state=_cdp_state,
    stop_grpc_server=stop_grpc_server,
    stop_cluster_heartbeat=stop_cluster_heartbeat,
    get_shutdown_event=_get_shutdown_event,
    version=VERSION,
    log_info=log.info,
    log_debug=log.debug,
)
_lifecycle_runtime = make_lifecycle(_lifecycle_ctx)
on_startup = _lifecycle_runtime.on_startup
on_cleanup = _lifecycle_runtime.on_cleanup


# ============================================================================
# AUTH HELPER
# ============================================================================
# check_auth/require_auth implementations live in arena/auth/runtime.py.
check_auth = _auth_runtime.check_auth
require_auth = _auth_runtime.require_auth


_gateway_handler_registry = build_context_handlers(
    GatewayHandlerContext,
    make_gateway_handlers,
    {
        "require_auth": require_auth,
        "record_request": _record_request,
        "cors_json_response": _cors_json_response,
        "executor": _EXECUTOR,
        "handle_rpc": handle_rpc,
        "subprocess_kwargs": _subprocess_kwargs,
    },
    {
        "handle_gateway_index": "index",
        "handle_gateway_tools": "tools",
        "handle_gateway_run": "run",
        "handle_gateway_tool": "tool",
    },
)
globals().update(_gateway_handler_registry)


_mcp_handler_registry = build_context_handlers(
    McpHandlerContext,
    make_mcp_handlers,
    {
        "require_auth": require_auth,
        "record_request": _record_request,
        "cors_json_response": _cors_json_response,
        "handle_rpc": handle_rpc,
        "log_error": log.error,
    },
    {
        "handle_mcp_post": "mcp_post",
        "handle_mcp_delete": "mcp_delete",
        "handle_sse": "sse",
        "handle_sse_messages": "sse_messages",
        "handle_ws": "ws",
    },
)
globals().update(_mcp_handler_registry)


_api_v2_handler_registry = build_context_handlers(
    ApiV2HandlerContext,
    make_v2_handlers,
    {
        "require_auth": require_auth,
        "record_request": _record_request,
        "cors_json_response": _cors_json_response,
        "version": VERSION,
        "metrics": BRIDGE_METRICS,
        "cdp_state": _cdp_state,
        "watchdog_state": _watchdog_state,
        "cluster_state": _cluster_state,
        "cluster_config": _cluster_config,
        "tls_config": _tls_config,
        "profiles_dir": _PROFILES_DIR,
        "sandbox_config": _sandbox_config,
        "blocked_reason": blocked_reason,
        "first_word": first_word,
        "decode_output": decode_output,
        "run_sandboxed": _run_sandboxed,
        "cfg_get_max_timeout": cfg_get_max_timeout,
        "audit": audit,
        "emit_event": emit_event,
        "now": time.time,
    },
    {
        "handle_v2_index": "index",
        "handle_v2_status": "status",
        "handle_v2_health": "health",
        "handle_v2_browser_status": "browser_status",
        "handle_v2_exec": "exec",
        "handle_v2_deprecations": "deprecations",
    },
)
globals().update(_api_v2_handler_registry)


_batch_handler_registry = build_context_handlers(
    BatchHandlerContext,
    make_batch_handlers,
    {
        "require_auth": require_auth,
        "record_request": _record_request,
        "cors_json_response": _cors_json_response,
        "emit_event": emit_event,
        "now": time.time,
    },
    {"handle_v1_batch": "batch"},
)
globals().update(_batch_handler_registry)


_alert_handler_registry = build_context_handlers(
    AlertsHandlerContext,
    make_alert_handlers,
    {
        "require_auth": require_auth,
        "record_request": _record_request,
        "cors_json_response": _cors_json_response,
        "metrics": BRIDGE_METRICS,
        "watchdog_state": _watchdog_state,
        "cdp_state": _cdp_state,
        "rate_limit_lock": _rate_limit_lock,
        "rate_limit_store": _rate_limit_store,
        "rate_limit_window": _rate_limit_window,
        "rate_limit_max": _rate_limit_max,
        "now": time.time,
        "log_info": log.info,
    },
    {"handle_v1_alerts": "alerts"},
)
globals().update(_alert_handler_registry)


_rate_limit_handler_registry = build_context_handlers(
    RateLimitHandlerContext,
    make_rate_limit_handlers,
    {
        "require_auth": require_auth,
        "record_request": _record_request,
        "cors_json_response": _cors_json_response,
        "update_rate_limit_config": update_rate_limit_config,
        "rate_limit_stats": rate_limit_stats,
        "log_info": log.info,
    },
    {"handle_v1_ratelimit": "ratelimit"},
)
globals().update(_rate_limit_handler_registry)


_tls_handler_registry = build_context_handlers(
    TlsHandlerContext,
    make_tls_handlers,
    {
        "require_auth": require_auth,
        "record_request": _record_request,
        "cors_json_response": _cors_json_response,
        "generate_self_signed_cert": _generate_self_signed_cert,
        "get_tailscale_cert": _get_tailscale_cert,
        "log_info": log.info,
    },
    {"handle_v1_tls": "tls"},
)
globals().update(_tls_handler_registry)


_sandbox_handler_registry = build_context_handlers(
    SandboxHandlerContext,
    make_sandbox_handlers,
    {
        "require_auth": require_auth,
        "record_request": _record_request,
        "cors_json_response": _cors_json_response,
        "blocked_reason": blocked_reason,
        "first_word": first_word,
        "run_sandboxed": _run_sandboxed,
        "audit": audit,
        "emit_event": emit_event,
    },
    {"handle_v1_sandbox": "sandbox"},
)
globals().update(_sandbox_handler_registry)


_cluster_handler_registry = build_context_handlers(
    ClusterHandlerContext,
    make_cluster_handlers,
    {
        "require_auth": require_auth,
        "record_request": _record_request,
        "cors_json_response": _cors_json_response,
        "get_node_id": _get_node_id,
        "start_heartbeat": lambda: start_cluster_heartbeat(log_error=log.error),
        "stop_heartbeat": stop_cluster_heartbeat,
        "audit": audit,
        "log_info": log.info,
    },
    {"handle_v1_cluster": "cluster"},
)
globals().update(_cluster_handler_registry)


_profile_handler_registry = build_context_handlers(
    ProfileHandlerContext,
    make_profile_handlers,
    {
        "require_auth": require_auth,
        "record_request": _record_request,
        "cors_json_response": _cors_json_response,
        "profiles_dir": _PROFILES_DIR,
        "ensure_profiles_dir": _ensure_profiles_dir,
        "cdp_state": _cdp_state,
        "cdp_active_tab": lambda *args, **kwargs: _cdp_active_tab(*args, **kwargs),
        "version": VERSION,
        "utc_now": utc_now,
        "audit": audit,
        "emit_event": emit_event,
        "log_warning": log.warning,
    },
    {
        "handle_v1_profiles": "profiles",
        "handle_v1_profiles_load": "load",
    },
)
globals().update(_profile_handler_registry)


_grpc_handler_registry = build_context_handlers(
    GrpcHandlerContext,
    make_grpc_handlers,
    {
        "require_auth": require_auth,
        "record_request": _record_request,
        "cors_json_response": _cors_json_response,
        "server_task": _grpc_server_task,
        "start_server": lambda cfg: start_grpc_server(cfg, log_info=log.info, log_error=log.error),
        "stop_server": stop_grpc_server,
    },
    {"handle_v1_grpc": "grpc"},
)
globals().update(_grpc_handler_registry)


_event_handler_registry = build_context_handlers(
    EventHandlerContext,
    make_event_handlers,
    {
        "require_auth": require_auth,
        "version": VERSION,
        "utc_now": utc_now,
        "log_info": log.info,
    },
    {"handle_v1_events": "events"},
)
globals().update(_event_handler_registry)


_watchdog_handler_registry = build_context_handlers(
    WatchdogHandlerContext,
    make_watchdog_handlers,
    {
        "require_auth": require_auth,
        "record_request": _record_request,
        "cors_json_response": _cors_json_response,
        "metrics": BRIDGE_METRICS,
        "now": time.time,
        "log_info": log.info,
    },
    {"handle_v1_watchdog": "watchdog"},
)
globals().update(_watchdog_handler_registry)


_gui_handler_registry = build_context_handlers(
    GuiHandlerContext,
    make_gui_handlers,
    {
        "cors_json_response": _cors_json_response,
        "bridge_dir": BRIDGE_DIR,
        "version": VERSION,
    },
    {
        "handle_gui": "gui",
        "handle_gui_v2": "gui_v2",
    },
)
globals().update(_gui_handler_registry)


_runtime_observability_handler_registry = build_context_handlers(
    RuntimeObservabilityHandlerContext,
    make_runtime_observability_handlers,
    {
        "require_auth": require_auth,
        "record_request": _record_request,
        "cors_json_response": _cors_json_response,
        "metrics": BRIDGE_METRICS,
        "metrics_lock": _metrics_lock,
        "active_processes": ACTIVE_PROCESSES,
        "cdp_state": _cdp_state,
        "watchdog_state": _watchdog_state,
        "event_subscribers": _event_subscribers,
        "tls_config": _tls_config,
        "grpc_config": _grpc_config,
        "cluster_state": _cluster_state,
        "sandbox_config": _sandbox_config,
        "otel_config": _otel_config,
        "log_file": LOG_FILE,
        "version": VERSION,
        "now": time.time,
        "log_error": log.error,
    },
    {
        "handle_v1_metrics": "metrics",
        "handle_prometheus_metrics": "prometheus_metrics",
        "handle_v1_logs": "logs",
    },
)
globals().update(_runtime_observability_handler_registry)


_tracing_handler_registry = build_context_handlers(
    TracingHandlerContext,
    make_tracing_handlers,
    {
        "require_auth": require_auth,
        "record_request": _record_request,
        "cors_json_response": _cors_json_response,
        "version": VERSION,
        "log_info": log.info,
    },
    {
        "handle_v1_tracing": "tracing",
        "handle_v1_traces_export": "traces_export",
    },
)
globals().update(_tracing_handler_registry)


_user_handler_registry = build_context_handlers(
    UserHandlerContext,
    make_user_handlers,
    {
        "require_auth": require_auth,
        "record_request": _record_request,
        "cors_json_response": _cors_json_response,
        "check_auth_with_role": check_auth_with_role,
        "list_users": _user_store.list_users_for_response,
        "add_or_update_user": _user_store.add_or_update_user,
        "remove_user": _user_store.remove_user,
        "token_generator": b64_token,
        "audit": audit,
        "log_info": log.info,
    },
    {"handle_v1_users": "users"},
)
globals().update(_user_handler_registry)


_file_handler_registry = build_context_handlers(
    FileHandlerContext,
    make_file_handlers,
    {
        "require_auth": require_auth,
        "record_request": _record_request,
        "cors_json_response": _cors_json_response,
        "audit": audit,
        "home": Path.home(),
        "bridge_py": Path(__file__).resolve(),
    },
    {
        "handle_v1_upload": "upload",
        "handle_v1_download": "download",
    },
)
globals().update(_file_handler_registry)


def _check_internet_sync() -> bool:
    return check_internet()

def _doctor_sync(token: str) -> dict:
    return run_doctor(
        version=VERSION,
        token=token,
        bridge_dir=BRIDGE_DIR,
        memory_dir=MEMORY_FILE.parent,
        missions_dir=MISSIONS_DIR,
        facts_count_fn=lambda: len(_load_facts()),
        internet_check_fn=_check_internet_sync,
        home_dir=Path.home(),
    )


def _play_beep_sync(beep_type: str, freq: int, dur: int) -> dict:
    return play_beep(beep_type, freq, dur, subprocess_kwargs_fn=_subprocess_kwargs)
def _sysinfo_cim_sync() -> tuple[int, int]:
    return sysinfo_cim_cpu_counts(subprocess_kwargs_fn=_subprocess_kwargs)

def _sysinfo_sync(root) -> dict:
    return collect_sysinfo(
        root=root,
        clean_platform_name_fn=get_clean_platform_name,
        subprocess_kwargs_fn=_subprocess_kwargs,
    )

def common_status(cfg: dict) -> dict:
    return {
        "ok": True,
        "service": "arena-unified-bridge",
        "version": VERSION,
        "host": socket.gethostname(),
        "platform": get_clean_platform_name(),
        "python": sys.version.split()[0],
        "profile": cfg["profile"],
        "root": str(cfg["root"]),
        "auth_required_for_exec": True,
        "active_exec": cfg["active_exec"],
        "max_concurrent": cfg["max_concurrent"],
        "audit": str(AUDIT),
    }


_system_handler_registry = build_system_handlers(SystemWiringContext(
    require_auth=require_auth,
    record_request=_record_request,
    cors_json_response=_cors_json_response,
    executor=_EXECUTOR,
    common_status=lambda cfg: common_status(cfg),
    version=VERSION,
    clean_platform_name=get_clean_platform_name,
    doctor_sync=_doctor_sync,
    sysinfo_sync=_sysinfo_sync,
    play_beep_sync=_play_beep_sync,
))
globals().update(_system_handler_registry)


_admin_handler_registry = build_admin_handlers(AdminWiringContext(
    require_auth=require_auth,
    record_request=_record_request,
    cors_json_response=_cors_json_response,
    executor=_EXECUTOR,
    audit=audit,
    default_token_file=TOKEN_FILE,
    root_agent=ROOT_AGENT,
    subprocess_kwargs=_subprocess_kwargs,
))
globals().update(_admin_handler_registry)


_public_handler_registry = build_public_handlers(PublicWiringContext(
    record_request=_record_request,
    cors_json_response=_cors_json_response,
    metrics=BRIDGE_METRICS,
    version=VERSION,
    now=time.time,
    hostname=socket.gethostname,
    bridge_port=_get_bridge_port,
))
globals().update(_public_handler_registry)


# ============================================================================
# HANDLERS — Public
# ============================================================================
# Public index and health handlers now live in arena/public/handlers.py.



def _hwinfo_sync():
    """Collect extended hardware info. Cross-platform."""
    return collect_legacy_hwinfo(subprocess_kwargs_fn=_subprocess_kwargs)


def _hardware_from_inventory_sync(timeout: int = 45) -> dict:
    """Return one normalized hardware/system inventory payload."""
    inv_result = _inventory_sync(None, "json", timeout)
    return hardware_from_inventory_result(inv_result, legacy_hwinfo_fn=_hwinfo_sync)


# --- /v1/inventory GET — Full system inventory via scripts/inventory.py ---

def _inventory_sync(section: str | None = None, fmt: str = "text", timeout: int = 30) -> dict:
    """Run inventory.py and return the result."""
    return run_inventory(
        bridge_dir=BRIDGE_DIR,
        root_agent=ROOT_AGENT,
        section=section,
        fmt=fmt,
        timeout=timeout,
        python_executable=sys.executable or "python3",
    )


_hardware_handler_ctx = HandlerContext(
    require_auth=require_auth,
    record_request=_record_request,
    cors_json_response=_cors_json_response,
    executor=_EXECUTOR,
    slow_executor=_SLOW_EXECUTOR,
    inventory_sync=_inventory_sync,
    hardware_sync=_hardware_from_inventory_sync,
)
_hardware_handlers = make_hardware_handlers(_hardware_handler_ctx)
export_handler_attrs(globals(), _hardware_handlers, {"handle_v1_inventory": "inventory", "handle_v1_hardware": "hardware", "handle_v1_hwinfo": "hwinfo"})


_exec_handler_ctx = ExecHandlerContext(
    require_auth=require_auth,
    record_request=_record_request,
    cors_json_response=_cors_json_response,
    audit=audit,
    blocked_reason=blocked_reason,
    control_check=_control_check,
    is_input_injection_cmd=_is_input_injection_cmd,
    first_word=first_word,
    under_root=under_root,
    decode_output=decode_output,
    run_shell_command=run_shell_command,
    active_processes=ACTIVE_PROCESSES,
    active_processes_snapshot=active_processes_snapshot,
    cautious_allow=CAUTIOUS_ALLOW,
    default_max_output=DEFAULT_MAX_OUTPUT,
)
_exec_handlers = make_exec_handlers(_exec_handler_ctx)
export_handler_attrs(globals(), _exec_handlers, {"handle_v1_ps": "ps", "handle_v1_exec": "exec", "handle_v1_kill": "kill"})






















# ============================================================================
# HANDLER — Dashboard GUI
# ============================================================================
# Dashboard GUI templates/handlers now live in arena/gui/handlers.py.


# ============================================================================
# HANDLERS — Dashboard API endpoints
# ============================================================================

_memory_runtime_ctx = MemoryRuntimeContext(
    db_path=MEMORY_DB,
    jsonl_path=MEMORY_FILE,
    audit_path=AUDIT,
    read_tail=read_tail,
    utc_now=utc_now,
    log_error=log.error,
)
_memory_runtime = make_memory_runtime(_memory_runtime_ctx)
init_memory_db = _memory_runtime.init_memory_db
_load_facts = _memory_runtime.load_facts
_search_facts_paged = _memory_runtime.search_facts_paged
_write_fact = _memory_runtime.write_fact
_delete_fact = _memory_runtime.delete_fact
_recall_sync = _memory_runtime.recall_sync
_recall_digest_sync = _memory_runtime.recall_digest_sync








_resource_runtime_ctx = ResourceRuntimeContext(
    missions_dir=MISSIONS_DIR,
    reports_dir=REPORTS_DIR,
    hooks_dir=HOOKS_DIR,
    agents_dir=AGENTS_DIR,
    subagents_dir=SUBAGENTS_DIR,
    bin_dir=BIN,
    subprocess_kwargs=_subprocess_kwargs,
)
_resource_runtime = make_resource_runtime(_resource_runtime_ctx)
_list_missions_sync = _resource_runtime.list_missions_sync
_list_reports_sync = _resource_runtime.list_reports_sync


_browser_runtime_ctx = BrowserRuntimeContext(
    version=VERSION,
    validate_url=_validate_url,
)
_browser_runtime = make_browser_runtime(_browser_runtime_ctx)
_browser_search_sync = _browser_runtime.browser_search_sync
_browser_read_sync = _browser_runtime.browser_read_sync


# ============================================================================
# HANDLERS — v1.5.0 New Endpoints
# ============================================================================

# --- /v1/service/info GET — What manages this bridge process? ---














# --- /v1/sys/svc GET — Service status ---





def _capabilities_sync() -> dict:
    """Machine-readable capability map for agents."""
    return build_capabilities(
        version=VERSION,
        cdp_module_available=_get_cdp_module() is not None,
        cdp_connected=bool(_cdp_state.get("connected")),
        desktop_env=_detect_desktop_env(),
        service_info_fn=_service_info_sync,
        sys_svc_fn=_sys_svc_sync,
    )


_service_handler_registry = build_service_handlers(ServiceWiringContext(
    require_auth=require_auth,
    record_request=_record_request,
    cors_json_response=_cors_json_response,
    executor=_EXECUTOR,
    service_info_sync=_service_info_sync,
    sys_svc_sync=_sys_svc_sync,
    capabilities_sync=_capabilities_sync,
    spawn_respawn_helper=_spawn_respawn_helper,
    audit=audit,
))
globals().update(_service_handler_registry)




# --- /v1/sys/funnel, token regeneration, Tailscale/Cloudflared tunnels ---
# Admin/network runtime helpers and handlers now live in arena/admin/. Wrappers
# preserve historical helper names for compatibility.


def _sys_funnel_sync() -> dict:
    return _sys_funnel_status_runtime(subprocess_kwargs=_subprocess_kwargs)


def _token_path() -> Path:
    return Path(os.environ.get("ARENA_TOKEN_FILE", str(TOKEN_FILE))).expanduser()


def _token_regen_sync(target_path: str = "") -> dict:
    return _token_regenerate_runtime(target_path, default_token_file=TOKEN_FILE)


def _tailscale_funnel_action_sync(action: str, port: int) -> dict:
    return _tailscale_funnel_action_runtime(action, port)


def _cloudflared_funnel_action_sync(action: str, port: int) -> dict:
    return _cloudflared_funnel_action_runtime(
        action,
        port,
        root_agent=ROOT_AGENT,
        subprocess_kwargs=_subprocess_kwargs,
    )


# --- /v1/restart POST — Graceful shutdown (scheduled task / systemd / launchd will respawn) ---





# --- /v1/config GET — Token-free configuration dump ---







# Browser fetch/search runtime wrappers live in arena/browser/runtime.py.
_browser_dump_sync = _browser_runtime.browser_dump_sync
_browser_fetch_sync = _browser_runtime.browser_fetch_sync
_browser_head_sync = _browser_runtime.browser_head_sync


_browser_fetch_handler_ctx = BrowserFetchHandlerContext(
    require_auth=require_auth,
    record_request=_record_request,
    cors_json_response=_cors_json_response,
    executor=_EXECUTOR,
    browser_search_sync=_browser_search_sync,
    browser_read_sync=_browser_read_sync,
    browser_dump_sync=_browser_dump_sync,
    browser_fetch_sync=_browser_fetch_sync,
    browser_head_sync=_browser_head_sync,
)
_browser_fetch_handlers = make_browser_fetch_handlers(_browser_fetch_handler_ctx)
export_handler_attrs(globals(), _browser_fetch_handlers, {"handle_v1_browser_search": "search", "handle_v1_browser_read": "read", "handle_v1_browser_dump": "dump", "handle_v1_browser_fetch": "fetch", "handle_v1_browser_head": "head"})


_browser_browse_handler_ctx = BrowserBrowseHandlerContext(
    require_auth=require_auth,
    record_request=_record_request,
    cors_json_response=_cors_json_response,
    app_dir=APP_DIR,
    cdp_state=_cdp_state,
    get_cdp_module=_get_cdp_module,
    start_cdp_watcher=_start_cdp_watcher,
)
_browser_browse_handlers = make_browser_browse_handlers(_browser_browse_handler_ctx)
export_handler_attrs(globals(), _browser_browse_handlers, {"handle_v1_browser_browse": "browse"})


_cdp_basic_handler_ctx = CdpBasicHandlerContext(
    require_auth=require_auth,
    record_request=_record_request,
    cors_json_response=_cors_json_response,
    cdp_state=_cdp_state,
    get_cdp_module=_get_cdp_module,
    watcher_active=_cdp_watcher_active,
)
_cdp_basic_handlers = make_cdp_basic_handlers(_cdp_basic_handler_ctx)
export_handler_attrs(globals(), _cdp_basic_handlers, {"handle_v1_cdp_status": "status", "handle_v1_cdp_diag": "diag"})


_cdp_diagnostic_handler_ctx = CdpDiagnosticHandlerContext(
    require_auth=require_auth,
    record_request=_record_request,
    cors_json_response=_cors_json_response,
    executor=_EXECUTOR,
    get_cdp_module=_get_cdp_module,
    log_info=log.info,
    log_warning=log.warning,
    log_error=log.error,
)
_cdp_diagnostic_handlers = make_cdp_diagnostic_handlers(_cdp_diagnostic_handler_ctx)
export_handler_attrs(globals(), _cdp_diagnostic_handlers, {"handle_v1_cdp_raw_info": "raw_info", "handle_v1_cdp_test_launch": "test_launch", "handle_v1_cdp_test_ws": "test_ws"})


_cdp_session_handler_ctx = CdpSessionHandlerContext(
    require_auth=require_auth,
    record_request=_record_request,
    cors_json_response=_cors_json_response,
    cdp_state=_cdp_state,
    cdp_connect_lock=_cdp_connect_lock,
    get_cdp_module=_get_cdp_module,
    start_cdp_watcher=_start_cdp_watcher,
    stop_cdp_watcher=_stop_cdp_watcher,
    emit_event=emit_event,
    log_info=log.info,
    log_warning=log.warning,
)
_cdp_session_handlers = make_cdp_session_handlers(_cdp_session_handler_ctx)
export_handler_attrs(globals(), _cdp_session_handlers, {"handle_v1_cdp_connect": "connect", "handle_v1_cdp_disconnect": "disconnect"})





# ============================================================================
# HANDLERS — CDP (Chrome DevTools Protocol)
# ============================================================================

async def _cdp_active_tab(tab_id: Optional[str] = None):
    """Compatibility wrapper for CDP tab resolution during v3 migration."""
    return await _cdp_active_tab_impl(
        tab_id,
        cdp_state=_cdp_state,
        get_cdp_module=_get_cdp_module,
        cors_json_response=_cors_json_response,
        log_warning=log.warning,
    )


# ---- CDP Session Management ----

# Lightweight CDP status/diag handlers now live in
# arena/browser/cdp/handlers.py and are bound above via
# make_cdp_basic_handlers(...).


# CDP raw-info/test-launch/test-ws diagnostic handlers now live in
# arena/browser/cdp/diagnostics.py and are bound above via
# make_cdp_diagnostic_handlers(...).


# CDP connect/disconnect session handlers now live in
# arena/browser/cdp/session.py and are bound above via
# make_cdp_session_handlers(...).


_cdp_page_handler_ctx = CdpPageHandlerContext(
    require_auth=require_auth,
    record_request=_record_request,
    cors_json_response=_cors_json_response,
    cdp_state=_cdp_state,
    cdp_active_tab=_cdp_active_tab,
    default_max_output=DEFAULT_MAX_OUTPUT,
    log_debug=log.debug,
    log_warning=log.warning,
    log_error=log.error,
)
_cdp_page_handlers = make_cdp_page_handlers(_cdp_page_handler_ctx)
export_handler_attrs(globals(), _cdp_page_handlers, {"handle_v1_cdp_navigate": "navigate", "handle_v1_cdp_screenshot": "screenshot", "handle_v1_cdp_dom": "dom", "handle_v1_cdp_eval": "eval", "handle_v1_cdp_click": "click", "handle_v1_cdp_type": "type"})


# ---- CDP Page Operations ----
# Implementations moved to arena/browser/cdp/page.py and are bound above via
# make_cdp_page_handlers(...).

# CDP page action endpoint implementations moved to arena/browser/cdp/page.py.



# ============================================================================
# DESKTOP AUTOMATION (v2.4.0)
# ============================================================================
# Endpoints for controlling the desktop environment (Wayland/X11):
#   /v1/desktop/screenshot  — Take a screenshot of the desktop
#   /v1/desktop/click       — Click at coordinates on the desktop
#   /v1/desktop/type        — Type text on the desktop
#   /v1/desktop/key         — Press a key on the desktop
#   /v1/desktop/mouse       — Move mouse to coordinates
#   /v1/desktop/windows     — List open windows
# ============================================================================

















# ============================================================================
# Desktop: Active Window + Focus + Control Lease (v2.9.0)
# ============================================================================









_desktop_handler_ctx = DesktopHandlerContext(
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
_desktop_handlers = make_desktop_handlers(_desktop_handler_ctx)
export_handler_attrs(globals(), _desktop_handlers, {"handle_v1_desktop_screenshot": "screenshot", "handle_v1_desktop_click": "click", "handle_v1_desktop_type": "type", "handle_v1_desktop_key": "key", "handle_v1_desktop_mouse": "mouse", "handle_v1_desktop_windows": "windows", "handle_v1_desktop_active_window": "active_window", "handle_v1_desktop_focus": "focus"})


_control_lease_handler_ctx = ControlLeaseHandlerContext(
    require_auth=require_auth,
    record_request=_record_request,
    cors_json_response=_cors_json_response,
    control_state=_control_state,
    control_lock=_control_lock,
    utc_now=utc_now,
    log_info=log.info,
    log_warning=log.warning,
)
_control_lease_handlers = make_control_lease_handlers(_control_lease_handler_ctx)
export_handler_attrs(globals(), _control_lease_handlers, {"handle_v1_control_status": "status", "handle_v1_control_pause": "pause", "handle_v1_control_resume": "resume", "handle_v1_control_revoke": "revoke"})

# ---- Control Lease Endpoints (v2.9.0) ----
# Implementations moved to arena/control_handlers.py and are bound above via
# make_control_lease_handlers(...).

# Control lease endpoint implementations moved to arena/control_handlers.py.



_cdp_tabs_handler_ctx = CdpTabsHandlerContext(
    require_auth=require_auth,
    record_request=_record_request,
    cors_json_response=_cors_json_response,
    cdp_state=_cdp_state,
    log_debug=log.debug,
)
_cdp_tabs_handlers = make_cdp_tabs_handlers(_cdp_tabs_handler_ctx)
export_handler_attrs(globals(), _cdp_tabs_handlers, {"handle_v1_cdp_tabs": "tabs", "handle_v1_cdp_tabs_new": "new", "handle_v1_cdp_tabs_close": "close", "handle_v1_cdp_tabs_activate": "activate"})


# ---- CDP Tab Management ----
# Implementations moved to arena/browser/cdp/tabs.py and are bound above via
# make_cdp_tabs_handlers(...).

# CDP tab management endpoint implementations moved to arena/browser/cdp/tabs.py.


_cdp_cookies_handler_ctx = CdpCookiesHandlerContext(
    require_auth=require_auth,
    record_request=_record_request,
    cors_json_response=_cors_json_response,
    cdp_state=_cdp_state,
    cdp_active_tab=_cdp_active_tab,
    get_cdp_module=_get_cdp_module,
    log_info=log.info,
    log_warning=log.warning,
    log_error=log.error,
)
_cdp_cookies_handlers = make_cdp_cookies_handlers(_cdp_cookies_handler_ctx)
export_handler_attrs(globals(), _cdp_cookies_handlers, {"handle_v1_cdp_cookies_get": "get", "handle_v1_cdp_cookies_set": "set", "handle_v1_cdp_cookies_delete": "delete", "handle_v1_cdp_cookies_clear": "clear", "handle_v1_cdp_cookies_profiles": "profiles"})


# ---- CDP Cookie Management ----
# Implementations moved to arena/browser/cdp/cookies.py and are bound above via
# make_cdp_cookies_handlers(...).

async def _ensure_cookie_manager():
    """Compatibility wrapper for remaining CDP handlers during migration."""
    return await _cdp_ensure_cookie_manager(_cdp_cookies_handler_ctx)


# CDP cookie/profile endpoint implementations moved to arena/browser/cdp/cookies.py.


_cdp_network_handler_ctx = CdpNetworkHandlerContext(
    require_auth=require_auth,
    record_request=_record_request,
    cors_json_response=_cors_json_response,
    cdp_state=_cdp_state,
    cdp_active_tab=_cdp_active_tab,
    get_cdp_module=_get_cdp_module,
)
_cdp_network_handlers = make_cdp_network_handlers(_cdp_network_handler_ctx)
export_handler_attrs(globals(), _cdp_network_handlers, {"handle_v1_cdp_network_start": "start", "handle_v1_cdp_network_stop": "stop", "handle_v1_cdp_network_requests": "requests", "handle_v1_cdp_network_har": "har"})


# ---- CDP Network Monitoring ----
# Implementations moved to arena/browser/cdp/network.py and are bound above via
# make_cdp_network_handlers(...).

# CDP network monitoring endpoint implementations moved to arena/browser/cdp/network.py.


_cdp_intercept_handler_ctx = CdpInterceptHandlerContext(
    require_auth=require_auth,
    record_request=_record_request,
    cors_json_response=_cors_json_response,
    cdp_state=_cdp_state,
    cdp_active_tab=_cdp_active_tab,
    get_cdp_module=_get_cdp_module,
)
_cdp_intercept_handlers = make_cdp_intercept_handlers(_cdp_intercept_handler_ctx)
export_handler_attrs(globals(), _cdp_intercept_handlers, {"handle_v1_cdp_intercept_start": "start", "handle_v1_cdp_intercept_stop": "stop", "handle_v1_cdp_intercept_rule": "rule"})


# ---- CDP Network Interception ----
# Implementations moved to arena/browser/cdp/intercept.py and are bound above via
# make_cdp_intercept_handlers(...).

# CDP network interception endpoint implementations moved to arena/browser/cdp/intercept.py.


_cdp_advanced_handler_ctx = CdpAdvancedHandlerContext(
    require_auth=require_auth,
    record_request=_record_request,
    cors_json_response=_cors_json_response,
    cdp_state=_cdp_state,
    ensure_cookie_manager=_ensure_cookie_manager,
    watcher_active=_cdp_watcher_active,
    bridge_start_time=BRIDGE_METRICS["start_time"],
)
_cdp_advanced_handlers = make_cdp_advanced_handlers(_cdp_advanced_handler_ctx)
export_handler_attrs(globals(), _cdp_advanced_handlers, {"handle_v1_cdp_session_check": "session_check", "handle_v1_cdp_stealth_extract": "stealth_extract", "handle_v1_cdp_stealth_shot": "stealth_shot", "handle_v1_cdp_health": "health"})



# ---- CDP Session Health Check / Stealth / Health ----
# Implementations moved to arena/browser/cdp/advanced.py and are bound above via
# make_cdp_advanced_handlers(...).

async def _cdp_get_active_browser():
    """Compatibility wrapper for remaining code during CDP migration."""
    return await _cdp_get_active_browser_from_context(_cdp_advanced_handler_ctx)


# CDP session-check, stealth extract/shot, and health handlers moved to arena/browser/cdp/advanced.py.



# Memory recall helpers moved to arena/memory/runtime.py and bound above.


_memory_handler_ctx = MemoryHandlerContext(
    require_auth=require_auth,
    record_request=_record_request,
    cors_json_response=_cors_json_response,
    executor=_EXECUTOR,
    search_facts_paged=_search_facts_paged,
    write_fact=_write_fact,
    delete_fact=_delete_fact,
    recall_sync=_recall_sync,
    recall_digest_sync=_recall_digest_sync,
    audit=audit,
    utc_now=utc_now,
)
_memory_handlers = make_memory_handlers(_memory_handler_ctx)
export_handler_attrs(globals(), _memory_handlers, {"handle_v1_memory": "memory_get", "handle_v1_memory_set": "memory_set", "handle_v1_memory_delete": "memory_delete", "handle_v1_recall": "recall", "handle_v1_recall_digest": "recall_digest"})




# --- /v1/audit/stats GET — Audit statistics ---

def _audit_stats_sync() -> dict:
    return audit_stats(AUDIT)


_observability_handler_ctx = ObservabilityHandlerContext(
    require_auth=require_auth,
    record_request=_record_request,
    cors_json_response=_cors_json_response,
    executor=_EXECUTOR,
    audit_path=AUDIT,
    request_log_file=_REQ_LOG_FILE,
    read_tail=read_tail,
    read_request_log=read_request_log,
    audit_stats_sync=_audit_stats_sync,
    load_webhooks=_load_webhooks,
    save_webhooks=_save_webhooks,
    normalize_webhooks_config=normalize_webhooks_config,
    audit=audit,
)
_observability_handlers = make_observability_handlers(_observability_handler_ctx)
export_handler_attrs(globals(), _observability_handlers, {"handle_v1_audit": "audit", "handle_v1_audit_stats": "audit_stats", "handle_v1_audit_log": "audit_log", "handle_v1_webhooks_get": "webhooks_get", "handle_v1_webhooks_set": "webhooks_set"})




# --- /v1/tasks runtime compatibility wrappers ---

_task_queue_runtime_ctx = TaskQueueRuntimeContext(
    inbox=INBOX,
    running=RUNNING,
    done=DONE,
    failed=FAILED,
    default_cwd=str(Path.home()),
    now=utc_now,
)
_task_queue_runtime = make_task_queue_runtime(_task_queue_runtime_ctx)
_tasks_list_sync = _task_queue_runtime.tasks_list_sync
_task_submit_sync = _task_queue_runtime.task_submit_sync
_tasks_clean_sync = _task_queue_runtime.tasks_clean_sync


_task_handler_ctx = TaskHandlerContext(
    require_auth=require_auth,
    record_request=_record_request,
    cors_json_response=_cors_json_response,
    executor=_EXECUTOR,
    tasks_list_sync=_tasks_list_sync,
    task_submit_sync=_task_submit_sync,
    tasks_clean_sync=_tasks_clean_sync,
    audit=audit,
)
_task_handlers = make_task_handlers(_task_handler_ctx)
export_handler_attrs(globals(), _task_handlers, {"handle_v1_tasks_get": "tasks_get", "handle_v1_tasks_post": "tasks_post", "handle_v1_tasks_clean": "tasks_clean"})




# --- /v1/skills runtime compatibility wrappers ---

_skill_runtime_ctx = SkillRuntimeContext(
    skills_dir=lambda: SKILLS_DIR,
    root_agent=lambda: ROOT_AGENT,
    bin_dir=lambda: BIN,
    subprocess_kwargs=_subprocess_kwargs,
)
_skill_runtime = make_skill_runtime(_skill_runtime_ctx)
_skills_list_sync = _skill_runtime.skills_list_sync
_parse_skill_folder = _skill_runtime.parse_skill_folder_compat
_skill_install_sync = _skill_runtime.skill_install_sync
_normalize_third_party_skill_name = _skill_runtime.normalize_third_party_skill_name
_skill_uninstall_sync = _skill_runtime.skill_uninstall_sync
_skills_run_sync = _skill_runtime.skills_run_sync
_skill_path_is_safe = _skill_runtime.skill_path_is_safe


_skill_handler_ctx = SkillHandlerContext(
    require_auth=require_auth,
    record_request=_record_request,
    cors_json_response=_cors_json_response,
    executor=_EXECUTOR,
    skills_list_with_cache=_skills_list_sync_with_cache,
    skills_cache_reset=_skills_cache_reset,
    skill_install_sync=_skill_install_sync,
    skill_uninstall_sync=_skill_uninstall_sync,
    skills_run_sync=lambda *args, **kwargs: _skills_run_sync(*args, **kwargs),
    skill_path_is_safe=_skill_path_is_safe,
    audit=audit,
    log_info=log.info,
)
_skill_handlers = make_skill_handlers(_skill_handler_ctx)
export_handler_attrs(globals(), _skill_handlers, {"handle_v1_skills": "skills", "handle_v1_skills_install": "install", "handle_v1_skills_uninstall": "uninstall", "handle_v1_skills_run": "run", "handle_v1_skills_reload": "reload"})




# Resource listing/spawn/show runtime wrappers live in arena/resources/runtime.py.
_hooks_list_sync = _resource_runtime.hooks_list_sync
_agents_list_sync = _resource_runtime.agents_list_sync
_subagents_list_sync = _resource_runtime.subagents_list_sync
_subagents_spawn_sync = _resource_runtime.subagents_spawn_sync
_mission_show_sync = _resource_runtime.mission_show_sync


_resource_handler_ctx = ResourceHandlerContext(
    require_auth=require_auth,
    record_request=_record_request,
    cors_json_response=_cors_json_response,
    executor=_EXECUTOR,
    list_missions_sync=_list_missions_sync,
    list_reports_sync=_list_reports_sync,
    hooks_list_sync=_hooks_list_sync,
    agents_list_sync=_agents_list_sync,
    subagents_list_sync=_subagents_list_sync,
    mission_show_sync=_mission_show_sync,
    subagent_spawn_sync=_subagents_spawn_sync,
    audit=audit,
)
_resource_handlers = make_resource_handlers(_resource_handler_ctx)
export_handler_attrs(globals(), _resource_handlers, {"handle_v1_missions": "missions", "handle_v1_reports": "reports", "handle_v1_hooks": "hooks", "handle_v1_agents": "agents", "handle_v1_subagents": "subagents", "handle_v1_subagents_spawn": "subagents_spawn", "handle_v1_mission_show": "mission_show"})




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
# GRACEFUL SHUTDOWN
# ============================================================================

_shutdown_event: asyncio.Event | None = None
_signal_handler = _lifecycle_runtime.signal_handler


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
