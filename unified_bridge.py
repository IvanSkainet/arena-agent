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
from arena.browser.cdp.handlers import make_cdp_basic_handlers  # noqa: E402,F401
from arena.browser.cdp.diagnostics import make_cdp_diagnostic_handlers  # noqa: E402,F401
from arena.browser.cdp.session import make_cdp_session_handlers  # noqa: E402,F401
from arena.browser.cdp.page import make_cdp_page_handlers  # noqa: E402,F401
from arena.browser.cdp.tabs import make_cdp_tabs_handlers  # noqa: E402,F401
from arena.browser.cdp.cookies import ensure_cookie_manager as _cdp_ensure_cookie_manager, make_cdp_cookies_handlers  # noqa: E402,F401
from arena.resources.listing import (  # noqa: E402,F401
    list_agents,
    list_hooks,
    list_missions,
    list_reports,
    list_subagents,
    show_mission,
)
from arena.resources.handlers import make_resource_handlers  # noqa: E402,F401
from arena.resources.subagents import spawn_subagent  # noqa: E402,F401
from arena.memory.handlers import make_memory_handlers  # noqa: E402,F401
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
from arena.handler_context import HandlerContext, ServiceHandlerContext, TaskHandlerContext, SkillHandlerContext, DesktopHandlerContext, ControlLeaseHandlerContext, BrowserFetchHandlerContext, BrowserBrowseHandlerContext, CdpBasicHandlerContext, CdpDiagnosticHandlerContext, CdpSessionHandlerContext, CdpPageHandlerContext, CdpTabsHandlerContext, CdpCookiesHandlerContext, ResourceHandlerContext, MemoryHandlerContext, ObservabilityHandlerContext, SystemHandlerContext, UserHandlerContext, FileHandlerContext, ExecHandlerContext, GatewayHandlerContext, TracingHandlerContext, ApiV2HandlerContext, BatchHandlerContext, AlertsHandlerContext, RateLimitHandlerContext, TlsHandlerContext, SandboxHandlerContext, ClusterHandlerContext, ProfileHandlerContext, GrpcHandlerContext, EventHandlerContext, WatchdogHandlerContext, GuiHandlerContext, McpHandlerContext, RuntimeObservabilityHandlerContext, PublicHandlerContext, AdminHandlerContext  # noqa: E402,F401
from arena.inventory.handlers import make_hardware_handlers  # noqa: E402,F401
from arena.service.handlers import make_service_handlers  # noqa: E402,F401
from arena.tasks.handlers import make_task_handlers  # noqa: E402,F401


def _ensure_session_env() -> None:
    """Ensure session environment variables are set in os.environ.
    
    When running inside a systemd user service, the environment may be minimal
    even if Environment= is set in the unit file (race conditions, older systemd).
    This function ensures critical variables are set so the bridge itself
    (not just child processes) has access to them.
    """
    if os.name == "nt":
        return  # Not applicable on Windows
    
    uid = os.getuid()
    
    if not os.environ.get("XDG_RUNTIME_DIR"):
        xdg = f"/run/user/{uid}"
        if os.path.isdir(xdg):
            os.environ["XDG_RUNTIME_DIR"] = xdg
    
    if not os.environ.get("DBUS_SESSION_BUS_ADDRESS"):
        dbus_path = f"/run/user/{uid}/bus"
        if os.path.exists(dbus_path):
            os.environ["DBUS_SESSION_BUS_ADDRESS"] = f"unix:path={dbus_path}"
    
    if not os.environ.get("DISPLAY") and os.path.exists("/tmp/.X11-unix"):
        try:
            for xfile in os.listdir("/tmp/.X11-unix"):
                if xfile.startswith("X"):
                    os.environ["DISPLAY"] = f":{xfile[1:]}"
                    break
        except Exception:
            pass
    
    if not os.environ.get("WAYLAND_DISPLAY") and os.environ.get("XDG_RUNTIME_DIR"):
        wayland_sock = os.path.join(os.environ["XDG_RUNTIME_DIR"], "wayland-0")
        if os.path.exists(wayland_sock):
            os.environ["WAYLAND_DISPLAY"] = "wayland-0"


def _load_config_file() -> dict:
    """Load optional bridge.yml configuration file.
    
    Looks for bridge.yml in:
    1. $ARENA_AGENT_HOME/bridge.yml
    2. $HOME/arena-bridge/bridge.yml
    3. ./bridge.yml
    
    Returns empty dict if no config file found.
    """
    search_paths = []
    env_home = os.environ.get("ARENA_AGENT_HOME")
    if env_home:
        search_paths.append(Path(env_home) / "bridge.yml")
    search_paths.append(Path.home() / "arena-bridge" / "bridge.yml")
    search_paths.append(Path("bridge.yml"))
    
    for path in search_paths:
        if path.exists():
            try:
                import yaml
                with open(path) as f:
                    cfg = yaml.safe_load(f) or {}
                log.info("[Config] Loaded configuration from %s", path)
                return cfg
            except ImportError:
                # No PyYAML — try JSON fallback
                json_path = path.with_suffix('.json')
                if json_path.exists():
                    try:
                        import json as _json
                        with open(json_path) as f:
                            cfg = _json.load(f) or {}
                        log.info("[Config] Loaded JSON configuration from %s", json_path)
                        return cfg
                    except Exception:
                        pass
                log.debug("[Config] bridge.yml found at %s but PyYAML not installed, skipping", path)
                return {}
            except Exception as e:
                log.warning("[Config] Failed to load %s: %s", path, e)
                return {}
    return {}


def _get_bridge_port() -> int:
    """Get the port the bridge is running on (from config or default 8765)."""
    try:
        return int(os.environ.get("ARENA_PORT", "8765"))
    except (ValueError, TypeError):
        return 8765


# Version, paths and limits now live in arena/constants.py (re-exported near the
# top of this file). Runtime state stays here.

# ============================================================================
# STRUCTURED LOGGING
# ============================================================================

LOG_FILE = APP_DIR / "bridge.log"


def _setup_logging() -> logging.Logger:
    """Configure structured logging with file rotation and console output."""
    logger = logging.getLogger("arena-bridge")
    logger.setLevel(logging.DEBUG)

    # Prevent duplicate handlers on reload
    if logger.handlers:
        return logger

    # Structured format: timestamp LEVEL [component] message
    fmt = logging.Formatter(
        "%(asctime)s %(levelname)-5s [%(name)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )

    # Console handler (INFO level)
    ch = logging.StreamHandler(sys.stderr)
    ch.setLevel(logging.INFO)
    ch.setFormatter(fmt)
    logger.addHandler(ch)

    # File handler with rotation (DEBUG level, 5MB x 5 files)
    try:
        APP_DIR.mkdir(parents=True, exist_ok=True)
        fh = logging.handlers.RotatingFileHandler(
            str(LOG_FILE),
            maxBytes=5 * 1024 * 1024,
            backupCount=5,
            encoding="utf-8"
        )
        fh.setLevel(logging.DEBUG)
        fh.setFormatter(fmt)
        logger.addHandler(fh)
    except Exception:
        # If file logging fails, continue with console only
        pass

    return logger


log = _setup_logging()


# ============================================================================
# CUSTOM EXCEPTIONS (structured error codes for API responses)
# ============================================================================

class BridgeError(Exception):
    """Base exception for all bridge errors. Carries an error_code and HTTP status."""
    error_code: str = "BRIDGE_ERROR"
    http_status: int = 500

    def __init__(self, message: str = "", error_code: str = "", http_status: int = 0):
        super().__init__(message)
        if error_code:
            self.error_code = error_code
        if http_status:
            self.http_status = http_status

    def to_dict(self) -> dict:
        return {
            "ok": False,
            "error": str(self),
            "error_code": self.error_code,
        }


class ValidationError(BridgeError):
    """Input validation failure (400)."""
    error_code = "VALIDATION_ERROR"
    http_status = 400


class AuthError(BridgeError):
    """Authentication failure (401)."""
    error_code = "AUTH_ERROR"
    http_status = 401


class ForbiddenError(BridgeError):
    """Action not allowed (403)."""
    error_code = "FORBIDDEN"
    http_status = 403


class NotFoundError(BridgeError):
    """Resource not found (404)."""
    error_code = "NOT_FOUND"
    http_status = 404


class BridgeTimeoutError(BridgeError):
    """Operation timed out (408)."""
    error_code = "TIMEOUT"
    http_status = 408


class ResourceError(BridgeError):
    """Resource limit exceeded or unavailable (429/503)."""
    error_code = "RESOURCE_ERROR"
    http_status = 503


# ============================================================================
# ERROR MIDDLEWARE (global exception handler)
# ============================================================================

@web.middleware
async def error_middleware(request: web.Request, handler):
    """Catch all unhandled exceptions, return structured JSON, log stack traces."""
    # Rate limiting (skip for lightweight/public endpoints)
    if request.path not in ("/health", "/metrics", "/gui", "/", "/favicon.ico", "/api-docs"):
        rl = _check_rate_limit_v2(request) or _check_rate_limit(request)
        if rl:
            return rl

    # Generate request ID for tracing
    # Generate or accept request ID (limit client-provided to 64 chars)
    req_id = (request.headers.get("X-Request-Id") or str(uuid.uuid4())[:8])[:64]
    request["req_id"] = req_id

    t0 = time.time()
    try:
        resp = await handler(request)
        duration = time.time() - t0
        log.debug("[%s] %s %s -> %d (%.3fs)", req_id, request.method,
                  request.path, resp.status, duration)
        # Log request/response for observability (Phase 3)
        _log_request_response(request.method, request.path, resp.status,
                              duration, req_id, request.remote or "")
        # Add request ID to response headers
        resp.headers["X-Request-Id"] = req_id
        # Phase 4: Add deprecation headers for deprecated endpoints
        deprecation = _DEPRECATED_ENDPOINTS.get(request.path)
        if deprecation:
            resp.headers["Deprecation"] = "true"
            resp.headers["Sunset"] = deprecation.get("removal_version", "2.0.0")
            resp.headers["Link"] = f'<{deprecation.get("replacement", "")}>; rel="successor-version"'
        # Phase 4: Add rate limit headers if available
        rl_headers = request.get("_rl_headers")
        if rl_headers:
            for k, v in rl_headers.items():
                resp.headers[k] = v
        # Phase 4: OpenTelemetry span recording
        if _otel_should_sample():
            trace_id = request.headers.get("traceparent", "").split("-")[1] if "-" in request.headers.get("traceparent", "") else _otel_trace_id()
            _otel_record_span(trace_id, req_id[:16], f"{request.method} {request.path}",
                              duration * 1000, {"http.method": request.method, "http.path": request.path,
                                                 "http.status_code": resp.status, "req_id": req_id},
                              status="OK" if resp.status < 400 else "ERROR")
        return resp
    except web.HTTPException as exc:
        duration = time.time() - t0
        log.debug("[%s] %s %s -> HTTPException %d (%.3fs)", req_id, request.method,
                  request.path, exc.status, duration)
        _log_request_response(request.method, request.path, exc.status,
                              duration, req_id, request.remote or "")
        # Add CORS and request ID headers to HTTP exceptions
        exc.headers["Access-Control-Allow-Origin"] = "*"
        exc.headers["Access-Control-Allow-Methods"] = "GET, POST, DELETE, OPTIONS"
        exc.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization, X-Arena-Token, Mcp-Session-Id"
        exc.headers["X-Request-Id"] = req_id
        raise
    except BridgeError as e:
        duration = time.time() - t0
        _record_request(duration=duration, is_error=True)
        _log_request_response(request.method, request.path, e.http_status,
                              duration, req_id, request.remote or "", error=str(e))
        log.warning("[%s] %s %s -> %s %s: %s (%.3fs)", req_id, request.method,
                    request.path, e.error_code, e.http_status, e, duration)
        return _cors_json_response(e.to_dict(), status=e.http_status,
                                   extra_headers={"X-Request-Id": req_id})
    except asyncio.CancelledError:
        raise
    except Exception as e:
        duration = time.time() - t0
        _record_request(duration=duration, is_error=True)
        _log_request_response(request.method, request.path, 500,
                              duration, req_id, request.remote or "", error=str(e))
        # Log full stack trace for debugging
        tb = _traceback.format_exc()
        log.error("[%s] %s %s UNHANDLED: %s\n%s", req_id, request.method,
                  request.path, e, tb)
        try:
            audit({"event": "unhandled_error", "req_id": req_id, "path": request.path,
                   "method": request.method, "error": repr(e), "tb_snippet": tb[:2000]})
        except Exception:
            pass  # Don't let audit failure crash the error handler
        return _cors_json_response({
            "ok": False,
            "error": "Internal server error",
            "error_code": "INTERNAL_ERROR",
            "req_id": req_id,
        }, status=500, extra_headers={"X-Request-Id": req_id})


# Thread pool executor for running blocking I/O in async handlers
_EXECUTOR = concurrent.futures.ThreadPoolExecutor(max_workers=8, thread_name_prefix="bridge_io")
# Dedicated executor for potentially slow operations (hwinfo)
# to avoid blocking the main executor pool
_SLOW_EXECUTOR = concurrent.futures.ThreadPoolExecutor(max_workers=2, thread_name_prefix="bridge_slow")

# ============================================================================
# CDP (Chrome DevTools Protocol) — Lazy import & session state
# ============================================================================
_cdp_module = None

def _get_cdp_module():
    """Lazily import cdp_browser from scripts/ directory."""
    global _cdp_module
    if _cdp_module is not None:
        return _cdp_module

    # Try multiple locations for cdp_browser.py
    search_paths = [
        BRIDGE_DIR / "scripts",
    ]

    for scripts_dir in search_paths:
        cdp_path = scripts_dir / "cdp_browser.py"
        if cdp_path.exists():
            sys.path.insert(0, str(scripts_dir))
            break

    try:
        import cdp_browser
        _cdp_module = cdp_browser

        # Configure the cdp_browser logger to use the same handlers as the bridge logger.
        # Without this, cdp_browser's logger.info/error calls are silently dropped
        # because the "cdp_browser" logger has no handlers configured.
        bridge_logger = logging.getLogger("arena-bridge")
        cdp_logger = logging.getLogger("cdp_browser")
        cdp_logger.setLevel(logging.DEBUG)
        # Clear any existing handlers and copy bridge's handlers
        cdp_logger.handlers.clear()
        for handler in bridge_logger.handlers:
            cdp_logger.addHandler(handler)
        # Don't propagate to root logger (bridge handles it)
        cdp_logger.propagate = False
        log.info("[CDP] Configured cdp_browser logger with %d handler(s)", len(bridge_logger.handlers))

        return _cdp_module
    except ImportError as e:
        return None


# --- CDP Session State ---
_cdp_state: Dict[str, Any] = {
    "manager": None,           # CDPTabManager instance
    "monitor": None,           # CDPNetworkMonitor instance
    "interceptor": None,       # CDPNetworkInterceptor instance
    "cookie_mgr": None,        # CDPCookieManager instance
    "connected": False,
    "port": 9222,
    "headless": True,
    "reconnect_count": 0,      # Number of auto-reconnects performed
    "last_connect_time": None, # Timestamp of last successful connect
    "last_disconnect_reason": None,  # Reason for last disconnect
    "last_navigation_time": None,    # Timestamp of last navigate call (skip probes during nav)
    "_consecutive_probe_timeouts": 0, # Tolerate N slow probes before reconnecting
    "_consecutive_none_probes": 0,    # Tolerate N None probes before reconnecting
}

_cdp_connect_lock = asyncio.Lock()  # Prevent concurrent connect/disconnect
_cdp_watcher_task: Optional[asyncio.Task] = None  # Background watcher for auto-reconnect

# --- CDP Event-Loop Blockage Detector (v2.3.0) ---
_cdp_loop_healthy_ts: float = time.time()  # Last time the event loop was responsive
_cdp_loop_check_task: Optional[asyncio.Task] = None
CDP_LOOP_CHECK_INTERVAL = 5.0   # seconds between checks
CDP_LOOP_BLOCK_THRESHOLD = 30.0  # seconds before declaring blocked


# --- CDP Auto-Reconnect Watcher ---
async def _cdp_watcher_loop():
    """Background task that monitors CDP connection health and auto-reconnects.

    Checks every 10 seconds:
    1. Is the browser process still alive?
    2. Is the WebSocket connection still open?
    3. Can we still list tabs?

    If any check fails, attempts to reconnect automatically.
    """
    while True:
        try:
            await asyncio.sleep(10)

            if not _cdp_state["connected"] or _cdp_connect_lock.locked():
                continue

            mgr = _cdp_state.get("manager")
            if not mgr:
                continue

            needs_reconnect = False
            reason = ""

            # Check 1: Browser process alive (only if we launched it)
            if mgr._browser_proc and mgr._browser_proc.poll() is not None:
                needs_reconnect = True
                reason = f"Browser process exited (rc={mgr._browser_proc.returncode})"
                log.warning("[CDP-Watcher] %s", reason)

            # Check 2: Active tab WebSocket still open
            elif mgr.active_tab and not mgr.active_tab.connected:
                # Tab was connected but now isn't — try a quick re-check
                try:
                    cdp_mod = _get_cdp_module()
                    tabs = await asyncio.get_event_loop().run_in_executor(
                        None, cdp_mod.list_tabs, _cdp_state["port"]
                    )
                    if tabs:
                        needs_reconnect = True
                        reason = "Active tab WebSocket disconnected but browser still running"
                        log.warning("[CDP-Watcher] %s", reason)
                    else:
                        needs_reconnect = True
                        reason = "No tabs found — browser may have crashed"
                        log.warning("[CDP-Watcher] %s", reason)
                except Exception as e:
                    needs_reconnect = True
                    reason = f"Cannot reach browser debug port: {e}"
                    log.warning("[CDP-Watcher] %s", reason)

            # Check 3: Health probe — tolerant of heavy pages (v2.5.1: improved resilience)
            elif mgr.active_tab and mgr.active_tab.connected:
                # Skip probe if navigation was recently initiated (heavy page loading)
                last_nav = _cdp_state.get("last_navigation_time")
                if last_nav and (time.time() - last_nav) < 45:
                    log.debug("[CDP-Watcher] Skipping health probe — recent navigation (%.1fs ago)",
                              time.time() - last_nav)
                else:
                    try:
                        # v2.5.1: Use lighter-weight CDP command instead of eval_js.
                        # Runtime.evaluate runs JS and waits for the result, which can
                        # be blocked by heavy pages doing synchronous JS work. Instead,
                        # use a simple CDP ping (Target.getTargetInfo) that only checks
                        # if the WebSocket is alive without needing JS execution.
                        result = await asyncio.wait_for(
                            mgr.active_tab.send("Target.getTargetInfo"),
                            timeout=10  # 10s — pure WS round-trip, no JS execution
                        )
                        if result is None:
                            _cdp_state["_consecutive_none_probes"] = _cdp_state.get("_consecutive_none_probes", 0) + 1
                            if _cdp_state["_consecutive_none_probes"] >= 3:
                                needs_reconnect = True
                                reason = f"Health probe returned None {_cdp_state['_consecutive_none_probes']}x — WS likely stale"
                                log.warning("[CDP-Watcher] %s", reason)
                            else:
                                log.debug("[CDP-Watcher] Health probe None (%d/3 tolerated)",
                                          _cdp_state["_consecutive_none_probes"])
                        else:
                            _cdp_state["_consecutive_none_probes"] = 0
                            _cdp_state["_consecutive_probe_timeouts"] = 0
                    except asyncio.TimeoutError:
                        # v2.5.1: More tolerant — WS ping timing out once is not fatal.
                        # Heavy pages may block the CDP message loop briefly.
                        _cdp_state["_consecutive_probe_timeouts"] = _cdp_state.get("_consecutive_probe_timeouts", 0) + 1
                        if _cdp_state["_consecutive_probe_timeouts"] >= 3:
                            needs_reconnect = True
                            reason = f"Health probe timed out {_cdp_state['_consecutive_probe_timeouts']}x consecutively (10s each)"
                            log.warning("[CDP-Watcher] %s", reason)
                        else:
                            log.info("[CDP-Watcher] Health probe timed out (%d/3 tolerated) — heavy page?",
                                     _cdp_state["_consecutive_probe_timeouts"])
                    except ConnectionError:
                        needs_reconnect = True
                        reason = "Health probe got ConnectionError — WebSocket closed"
                        log.warning("[CDP-Watcher] %s", reason)
                    except Exception as e:
                        # v2.5.1: Some CDP errors (e.g. Target domain not available)
                        # are non-fatal. Only reconnect on consecutive failures.
                        _cdp_state["_consecutive_probe_errors"] = _cdp_state.get("_consecutive_probe_errors", 0) + 1
                        if _cdp_state["_consecutive_probe_errors"] >= 3:
                            needs_reconnect = True
                            reason = f"Health probe error {_cdp_state['_consecutive_probe_errors']}x: {e}"
                            log.warning("[CDP-Watcher] %s", reason)
                        else:
                            log.debug("[CDP-Watcher] Health probe error (%d/3 tolerated): %s",
                                      _cdp_state["_consecutive_probe_errors"], e)

            if needs_reconnect:
                log.info("[CDP-Watcher] Initiating auto-reconnect... reason: %s", reason)
                _cdp_state["last_disconnect_reason"] = reason

                # Try to gracefully close existing connection
                try:
                    if mgr:
                        await asyncio.wait_for(mgr.close(), timeout=5)
                except Exception as e:
                    log.warning("[CDP-Watcher] Close failed (non-fatal): %s", e)

                _cdp_state["connected"] = False
                _cdp_state["manager"] = None

                # Auto-reconnect
                try:
                    cdp = _get_cdp_module()
                    if cdp:
                        new_mgr = cdp.CDPTabManager(
                            port=_cdp_state["port"],
                            headless=_cdp_state["headless"],
                            auto_launch=True,
                        )
                        await asyncio.wait_for(new_mgr.connect(), timeout=60)
                        _cdp_state["manager"] = new_mgr
                        _cdp_state["connected"] = True
                        _cdp_state["reconnect_count"] += 1
                        _cdp_state["last_connect_time"] = datetime.now(timezone.utc).isoformat()
                        log.info("[CDP-Watcher] Auto-reconnect SUCCESSFUL (count=%d)",
                                 _cdp_state["reconnect_count"])
                    else:
                        log.error("[CDP-Watcher] Cannot reconnect: cdp_browser module not found")
                except asyncio.TimeoutError:
                    log.error("[CDP-Watcher] Auto-reconnect TIMED OUT (60s)")
                    _cdp_state["connected"] = False
                except Exception as e:
                    log.error("[CDP-Watcher] Auto-reconnect FAILED: %s", e)
                    _cdp_state["connected"] = False

        except asyncio.CancelledError:
            log.info("[CDP-Watcher] Cancelled — shutting down")
            break
        except Exception as e:
            log.error("[CDP-Watcher] Unexpected error: %s", e)


async def _cdp_loop_blockage_detector():
    """Detect when the asyncio event loop is blocked for too long (v2.3.0).

    Uses a simple liveness pattern: schedule a callback from the event loop
    and measure how long it actually takes to run. If the loop is blocked
    (e.g., by a hanging CDP operation), the callback will be delayed.
    Logs a CRITICAL warning if blocked > threshold seconds.
    """
    global _cdp_loop_healthy_ts
    while True:
        try:
            loop = asyncio.get_running_loop()
            start = time.monotonic()

            fut = loop.create_future()
            loop.call_soon(lambda: fut.set_result(None) if not fut.done() else None)
            await asyncio.wait_for(fut, timeout=5.0)

            delay = time.monotonic() - start
            _cdp_loop_healthy_ts = time.time()

            if delay > 2.0:
                log.warning("[CDP-LoopCheck] Event loop delayed %.2fs (threshold: 2s)", delay)

        except asyncio.TimeoutError:
            blocked_for = time.time() - _cdp_loop_healthy_ts
            log.critical(
                "[CDP-LoopCheck] EVENT LOOP APPEARS BLOCKED for %.1fs! "
                "This likely indicates a hanging CDP operation. "
                "Last healthy: %.1fs ago",
                blocked_for, time.time() - _cdp_loop_healthy_ts
            )
        except asyncio.CancelledError:
            break
        except Exception as e:
            log.error("[CDP-LoopCheck] Unexpected error: %s", e)

        await asyncio.sleep(CDP_LOOP_CHECK_INTERVAL)


def _start_cdp_watcher():
    """Start the CDP health watcher and loop blockage detector."""
    global _cdp_watcher_task, _cdp_loop_check_task
    if _cdp_watcher_task and not _cdp_watcher_task.done():
        return
    _cdp_watcher_task = asyncio.create_task(_cdp_watcher_loop())
    # Start event-loop blockage detector
    if not _cdp_loop_check_task or _cdp_loop_check_task.done():
        _cdp_loop_check_task = asyncio.create_task(_cdp_loop_blockage_detector())
    log.info("[CDP-Watcher] Started (with loop blockage detector)")


def _stop_cdp_watcher():
    """Stop the CDP health watcher and loop blockage detector."""
    global _cdp_watcher_task, _cdp_loop_check_task
    if _cdp_watcher_task and not _cdp_watcher_task.done():
        _cdp_watcher_task.cancel()
        _cdp_watcher_task = None
    if _cdp_loop_check_task and not _cdp_loop_check_task.done():
        _cdp_loop_check_task.cancel()
        _cdp_loop_check_task = None
    log.info("[CDP-Watcher] Stopped (including loop blockage detector)")


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
_USERS_FILE = APP_DIR / "users.json"
_user_store = UserStore(_USERS_FILE, log_warning=log.warning, log_debug=log.debug)

def _load_users() -> dict[str, dict]:
    return _user_store.load_users()


def check_auth_with_role(request: web.Request, required_role: str | None = None) -> tuple[bool, str]:
    return _user_store.check_auth_with_role(request, required_role=required_role)




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

def sanitize_audit_event(event: dict[str, Any]) -> dict[str, Any]:
    return audit_sanitize_event(event)


_WEBHOOKS_CACHE = None

def _load_webhooks() -> dict:
    return load_webhooks(WEBHOOKS_FILE)

def _save_webhooks(data: dict) -> None:
    return save_webhooks(WEBHOOKS_FILE, data)

def _fire_webhooks(event: dict) -> None:
    return fire_webhooks(event, load_fn=_load_webhooks, log_debug=log.debug)


def audit(event: dict[str, Any]) -> None:
    written = write_audit_event(event, audit_path=AUDIT, app_dir=APP_DIR, utc_now_fn=utc_now, lock=audit_lock)
    try:
        _SLOW_EXECUTOR.submit(_fire_webhooks, written)
    except Exception:
        pass


def read_tail(path: Path, lines: int = 100) -> list[str]:
    return audit_read_tail(path, lines)


# ============================================================================
# LOG ROTATION & DISK SAFETY (v2.1.0 — prevents disk fill)
# ============================================================================

_MAX_LOG_SIZE = 10 * 1024 * 1024  # 10MB — max size before forced rotation
_MAX_LOG_BACKUPS = 3               # keep up to .1, .2, .3 rotated copies

# All log files that the bridge creates and should be rotated
_LOG_FILES_TO_ROTATE = [
    APP_DIR / "bridge.log",
    APP_DIR / "requests.jsonl",
    APP_DIR / "audit.jsonl",
]


def _rotate_file_if_oversized(path: Path, max_bytes: int = _MAX_LOG_SIZE,
                               backups: int = _MAX_LOG_BACKUPS) -> bool:
    """Rotate a log file if it exceeds max_bytes. Returns True if rotated."""
    try:
        if not path.exists() or path.stat().st_size <= max_bytes:
            return False
        # Shift existing backups: .N → delete, .1 → .2, etc.
        for i in range(backups, 0, -1):
            old = Path(f"{path}.{i}")
            if old.exists():
                if i == backups:
                    old.unlink()
                else:
                    try:
                        old.rename(Path(f"{path}.{i + 1}"))
                    except OSError:
                        pass
        # Current → .1
        try:
            path.rename(Path(f"{path}.1"))
        except OSError:
            pass
        return True
    except Exception:
        return False


def _rotate_all_logs_on_startup() -> None:
    """Rotate any oversized log files at bridge startup."""
    rotated = []
    for lf in _LOG_FILES_TO_ROTATE:
        if _rotate_file_if_oversized(lf):
            rotated.append(lf.name)
    # Also rotate the Windows Tee-Object log if it exists
    for name in ("ArenaUnifiedBridge.log", "bridge_err.log"):
        for parent in (Path.home() / "arena-agent" / "logs",
                       Path.home() / "arena-bridge" / "logs",
                       APP_DIR / "logs"):
            lf = parent / name
            if _rotate_file_if_oversized(lf, max_bytes=_MAX_LOG_SIZE, backups=2):
                rotated.append(f"{parent.name}/{name}")
    if rotated:
        log.warning("[LogRotation] Rotated oversized log files at startup: %s", ", ".join(rotated))


def _check_disk_space() -> float:
    """Return disk usage percentage for the partition containing APP_DIR."""
    try:
        if sys.platform == "win32":
            import ctypes
            free_bytes = ctypes.c_ulonglong(0)
            total_bytes = ctypes.c_ulonglong(0)
            ctypes.windll.kernel32.GetDiskFreeSpaceExW(
                str(APP_DIR.drive), None, ctypes.pointer(total_bytes),
                ctypes.pointer(free_bytes))
            if total_bytes.value > 0:
                return round((1 - free_bytes.value / total_bytes.value) * 100, 1)
        else:
            stat = os.statvfs(str(APP_DIR.parent))
            total = stat.f_blocks * stat.f_frsize
            free = stat.f_bavail * stat.f_frsize
            if total > 0:
                return round((1 - free / total) * 100, 1)
    except Exception:
        pass
    return -1  # unknown


async def _log_cleanup_loop(app: web.Application) -> None:
    """Periodic background task: rotate oversized logs and warn on disk space."""
    _rotate_all_logs_on_startup()
    while True:
        try:
            await asyncio.sleep(1800)  # every 30 minutes
            # Rotate logs
            rotated = []
            for lf in _LOG_FILES_TO_ROTATE:
                if _rotate_file_if_oversized(lf):
                    rotated.append(lf.name)
            if rotated:
                log.info("[LogCleanup] Rotated: %s", ", ".join(rotated))
            # Check disk space
            pct = _check_disk_space()
            if pct >= 0 and pct > 90:
                log.critical("[DiskSpace] Disk usage at %.1f%%! Consider cleaning up files.", pct)
            elif pct >= 0 and pct > 80:
                log.warning("[DiskSpace] Disk usage at %.1f%%", pct)
        except asyncio.CancelledError:
            break
        except Exception as e:
            log.error("[LogCleanup] Error: %s", e)


# ============================================================================
# MCP TOOLS REGISTRY (from mcp_stream_server.py)
# ============================================================================

MCP_TOOLS = [
    {"name": "ping", "description": "Return pong (liveness)",
     "inputSchema": {"type": "object", "properties": {}}},
    {"name": "echo", "description": "Echo arguments back",
     "inputSchema": {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]}},
    {"name": "exec", "description": "Run shell command outside bridge cgroup (via sd-exec)",
     "inputSchema": {"type": "object", "properties": {
         "cmd": {"type": "string"}, "timeout": {"type": "integer", "default": 60}},
         "required": ["cmd"]}},
    {"name": "fs.read", "description": "Read file contents (utf-8)",
     "inputSchema": {"type": "object", "properties": {
         "path": {"type": "string"}, "max_bytes": {"type": "integer", "default": 200000}},
         "required": ["path"]}},
    {"name": "fs.write", "description": "Write file (utf-8). Creates directories.",
     "inputSchema": {"type": "object", "properties": {
         "path": {"type": "string"}, "content": {"type": "string"}}, "required": ["path", "content"]}},
    {"name": "fs.list", "description": "List directory entries",
     "inputSchema": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}},
    {"name": "browser.search", "description": "DuckDuckGo search via pure-Python (no chromium)",
     "inputSchema": {"type": "object", "properties": {
         "query": {"type": "string"}, "n": {"type": "integer", "default": 5}},
         "required": ["query"]}},
    {"name": "browser.read", "description": "Readability-extract clean text from URL",
     "inputSchema": {"type": "object", "properties": {"url": {"type": "string"}}, "required": ["url"]}},
    {"name": "browser.shot", "description": "Take headless chromium screenshot via sd-exec",
     "inputSchema": {"type": "object", "properties": {"url": {"type": "string"}}, "required": ["url"]}},
    {"name": "mem.set", "description": "Remember a fact",
     "inputSchema": {"type": "object", "properties": {
         "key": {"type": "string"}, "value": {"type": "string"},
         "tags": {"type": "array", "items": {"type": "string"}}}, "required": ["key", "value"]}},
    {"name": "mem.get", "description": "Recall facts matching query substring",
     "inputSchema": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}},
    {"name": "sys.status", "description": "Bridge/services/funnel status",
     "inputSchema": {"type": "object", "properties": {}}},
    {"name": "skill.list", "description": "List available agent skills",
     "inputSchema": {"type": "object", "properties": {}}},
    {"name": "skill.run", "description": "Run an agent skill: namespace/name with optional args",
     "inputSchema": {"type": "object", "properties": {
         "name": {"type": "string"}, "args": {"type": "array", "items": {"type": "string"}, "default": []}},
         "required": ["name"]}},
    {"name": "hooks.list", "description": "List configured hooks per event",
     "inputSchema": {"type": "object", "properties": {}}},
    {"name": "snapshot", "description": "Run system snapshot skill and return JSON path",
     "inputSchema": {"type": "object", "properties": {}}},
    {"name": "subagent.spawn", "description": "Spawn isolated subagent for delegated work; returns summary",
     "inputSchema": {"type": "object", "properties": {
         "cmd": {"type": "string"}, "name": {"type": "string"},
         "wait": {"type": "boolean", "default": True}, "timeout": {"type": "integer", "default": 300}},
         "required": ["cmd"]}},
    {"name": "subagent.list", "description": "List recent subagents",
     "inputSchema": {"type": "object", "properties": {}}},
    {"name": "memory.recall", "description": "Find relevant facts/snapshots/sessions by query (TF score)",
     "inputSchema": {"type": "object", "properties": {
         "query": {"type": "string"}, "top": {"type": "integer", "default": 5}},
         "required": ["query"]}},
    {"name": "memory.digest", "description": "Compact markdown digest of recent memory (facts/snapshots/subagents)",
     "inputSchema": {"type": "object", "properties": {}}},
]


def run_local(argv: list[str], timeout: int = 30) -> tuple[int, str, str]:
    """Run a command directly (no GUI/sandbox needed)."""
    p = subprocess.run(argv, capture_output=True, text=True, timeout=timeout, **_subprocess_kwargs())
    return p.returncode, p.stdout, p.stderr


def run_sd(argv: list[str], timeout: int = 60) -> tuple[int, str, str]:
    """Run command via sd-exec (Linux) or directly (Windows)."""
    if platform.system() == "Windows":
        p = subprocess.run(argv, capture_output=True, text=True, timeout=timeout, shell=True, **_subprocess_kwargs())
        return p.returncode, p.stdout, p.stderr
    else:
        sd = os.path.join(BIN, "sd-exec")
        p = subprocess.run([sd, "--timeout", str(timeout), "--"] + argv,
                           capture_output=True, text=True, timeout=timeout + 10, **_subprocess_kwargs())
        return p.returncode, p.stdout, p.stderr


def text_content(s: str) -> dict:
    return {"content": [{"type": "text", "text": s}]}


def call_tool(name: str, args: dict) -> dict:
    """MCP tool dispatcher."""
    try:
        if name == "ping":
            return text_content("pong")
        if name == "echo":
            return text_content(str(args.get("text", "")))
        if name == "exec":
            cmd = args.get("cmd", "")
            if not cmd:
                return {"isError": True, "content": [{"type": "text", "text": "ERROR: missing 'cmd' argument"}]}
            # Security: check blocked patterns (same as /v1/exec)
            block = blocked_reason(cmd)
            if block:
                return {"isError": True, "content": [{"type": "text", "text": f"BLOCKED: {block}"}]}
            # Security: check profile allowlist (only for cautious profile)
            profile = os.environ.get("ARENA_PROFILE", "owner-shell")
            if profile == "cautious":
                fw = first_word(cmd)
                if CAUTIOUS_ALLOW and fw not in CAUTIOUS_ALLOW and fw.rstrip(".exe") not in CAUTIOUS_ALLOW:
                    return {"isError": True, "content": [{"type": "text", "text": f"BLOCKED: command '{fw}' not in allowlist"}]}
            if platform.system() == "Windows":
                rc, out, err = run_sd(["cmd", "/c", cmd], timeout=args.get("timeout", 60))
            else:
                rc, out, err = run_sd(["bash", "-lc", cmd], timeout=args.get("timeout", 60))
            return text_content(json.dumps({"exit": rc, "stdout": out[-15000:], "stderr": err[-5000:]}, ensure_ascii=False))
        # Sensitive files that must never be read via MCP
        _MCP_BLOCKED_FILES = {"token.txt", "users.json", ".env", "id_rsa", "id_ed25519",
                               "id_ecdsa", "id_dsa", ".netrc", ".ssh_config"}

        if name == "fs.read":
            p = os.path.expanduser(args.get("path", ""))
            if not p:
                return {"isError": True, "content": [{"type": "text", "text": "ERROR: missing 'path' argument"}]}
            # Security: block reading sensitive files
            if Path(p).name in _MCP_BLOCKED_FILES:
                return {"isError": True, "content": [{"type": "text", "text": f"BLOCKED: reading {Path(p).name} is not allowed"}]}
            # Security: restrict to home directory
            resolved = Path(p).resolve()
            home = Path.home().resolve()
            if not under_root(resolved, home):
                return {"isError": True, "content": [{"type": "text", "text": "BLOCKED: path outside home directory"}]}
            try:
                with open(p, "rb") as f:
                    data = f.read(args.get("max_bytes", 200000))
                return text_content(data.decode("utf-8", "replace"))
            except PermissionError:
                return {"isError": True, "content": [{"type": "text", "text": "ERROR: permission denied"}]}
            except FileNotFoundError:
                return {"isError": True, "content": [{"type": "text", "text": "ERROR: file not found"}]}
        if name == "fs.write":
            p = os.path.expanduser(args.get("path", ""))
            content = args.get("content", "")
            if not p:
                return {"isError": True, "content": [{"type": "text", "text": "ERROR: missing 'path' argument"}]}
            # Security: block writing sensitive files
            if Path(p).name in _MCP_BLOCKED_FILES:
                return {"isError": True, "content": [{"type": "text", "text": f"BLOCKED: writing {Path(p).name} is not allowed"}]}
            # Security: restrict to home directory
            resolved = Path(p).resolve()
            home = Path.home().resolve()
            if not under_root(resolved, home):
                return {"isError": True, "content": [{"type": "text", "text": "BLOCKED: path outside home directory"}]}
            try:
                os.makedirs(os.path.dirname(p) or ".", exist_ok=True)
                with open(p, "w", encoding="utf-8") as f:
                    f.write(content)
                return text_content(f"wrote {len(content)} bytes to {p}")
            except PermissionError:
                return {"isError": True, "content": [{"type": "text", "text": "ERROR: permission denied"}]}
        if name == "fs.list":
            p = os.path.expanduser(args.get("path", ""))
            if not p:
                return {"isError": True, "content": [{"type": "text", "text": "ERROR: missing 'path' argument"}]}
            # Security: restrict to home directory
            resolved = Path(p).resolve()
            home = Path.home().resolve()
            if not under_root(resolved, home):
                return {"isError": True, "content": [{"type": "text", "text": "BLOCKED: path outside home directory"}]}
            try:
                return text_content(json.dumps(sorted(os.listdir(p))))
            except PermissionError:
                return {"isError": True, "content": [{"type": "text", "text": "ERROR: permission denied"}]}
            except FileNotFoundError:
                return {"isError": True, "content": [{"type": "text", "text": "ERROR: directory not found"}]}
        if name == "browser.search":
            rc, out, err = run_local([sys.executable, os.path.join(BIN, "py_browser.py"),
                                       "search", args.get("query", ""), "--n", str(args.get("n", 5))], timeout=30)
            return text_content(out or err)
        if name == "browser.read":
            rc, out, err = run_local([sys.executable, os.path.join(BIN, "py_browser.py"),
                                       "read", args.get("url", "")], timeout=30)
            return text_content(out or err)
        if name == "browser.shot":
            import shutil as _shutil
            shots = str(REPORTS_DIR / "shots")
            os.makedirs(shots, exist_ok=True)
            png = os.path.join(shots, f"mcp-{int(time.time())}.png")
            ud = os.path.join(tempfile.gettempdir(), f"cr-mcp-{os.getpid()}")
            chrome_candidates = [
                r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
                "msedge.exe", "chrome.exe",
                r"C:\Program Files\Google\Chrome\Application\chrome.exe",
                r"C:\Program Files\LibreWolf\librewolf.exe",
            ] if platform.system() == "Windows" else [
                "chromium", "chrome", "google-chrome", "google-chrome-stable",
                "librewolf", "brave", "firefox", "vivaldi",
            ]
            chrome_exe = next(
                ((_shutil.which(c) or (c if os.path.exists(c) else None))
                for c in chrome_candidates if _shutil.which(c) or os.path.exists(c)),
                None) or "chrome.exe"
            rc, out, err = run_sd([chrome_exe, "--headless=new", "--no-sandbox", "--disable-gpu",
                                    f"--user-data-dir={ud}", "--window-size=1366,768",
                                    f"--screenshot={png}", args.get("url", "")], timeout=45)
            return text_content(json.dumps({"ok": rc == 0, "screenshot": png, "url": args.get("url", "")}))
        if name == "mem.set":
            key = args.get("key", "")
            value = args.get("value", "")
            if not key:
                return {"isError": True, "content": [{"type": "text", "text": "ERROR: missing 'key' argument"}]}
            tags = args.get("tags") or []
            entry = {"key": key, "value": value, "tags": tags,
                     "timestamp": datetime.now(timezone.utc).isoformat()}
            _write_fact(entry)
            audit({"type": "memory_set", "key": key, "via": "mcp"})
            return text_content(json.dumps({"ok": True, "fact": entry}, ensure_ascii=False))
        if name == "mem.get":
            q = args.get("query", args.get("q", ""))
            facts = _load_facts()
            if q:
                import fnmatch as _fn
                q_low = q.lower()
                scored = []
                for f in facts:
                    if q_low in json.dumps(f, ensure_ascii=False).lower():
                        scored.append(f)
                facts = scored
            return text_content(json.dumps({"ok": True, "count": len(facts), "facts": facts[-50:]}, ensure_ascii=False))
        if name == "sys.status":
            cfg = _app_ref.get("cfg", {}) if _app_ref else {}
            return text_content(json.dumps(common_status(cfg), ensure_ascii=False))
        if name == "skill.list":
            result = _skills_list_sync_with_cache()
            skills = result.get("skills", [])
            return text_content(json.dumps({"ok": True, "count": len(skills), "skills": skills}, ensure_ascii=False))
        if name == "skill.run":
            sk = args.get("name", "")
            extra = args.get("args") or []
            result = _skills_run_sync(sk, list(extra))
            return text_content(json.dumps(result, ensure_ascii=False))
        if name == "hooks.list":
            hooks_dir = BRIDGE_DIR / "hooks"
            pre_dir = hooks_dir / "pre_skill.d"
            post_dir = hooks_dir / "post_skill.d"
            hooks = []
            for d, phase in [(pre_dir, "pre"), (post_dir, "post")]:
                if d.exists():
                    for f in sorted(d.iterdir()):
                        if f.is_file():
                            hooks.append({"phase": phase, "name": f.name, "path": str(f)})
            return text_content(json.dumps({"ok": True, "count": len(hooks), "hooks": hooks}, ensure_ascii=False))
        if name == "snapshot":
            result = _skills_run_sync("system/sys-snapshot", [])
            return text_content(json.dumps(result, ensure_ascii=False))
        if name == "subagent.spawn":
            cmd_args = [sys.executable, os.path.join(BIN, "subagent.py"), "spawn", args.get("cmd", "")]
            if args.get("name"):
                cmd_args += ["--name", args["name"]]
            if args.get("wait", True):
                cmd_args += ["--wait"]
            cmd_args += ["--timeout", str(args.get("timeout", 300))]
            rc, out, err = run_local(cmd_args, timeout=args.get("timeout", 300) + 30)
            return text_content(out or err)
        if name == "subagent.list":
            rc, out, err = run_local([sys.executable, os.path.join(BIN, "subagent.py"), "list"], timeout=10)
            return text_content(out or err)
        if name == "memory.recall":
            cmd_args = [sys.executable, os.path.join(BIN, "memory_recall.py"), "recall",
                        args.get("query", ""), "--top", str(args.get("top", 5))]
            rc, out, err = run_local(cmd_args, timeout=15)
            return text_content(out or err)
        if name == "memory.digest":
            rc, out, err = run_local([sys.executable, os.path.join(BIN, "memory_recall.py"), "digest"], timeout=15)
            return text_content(out or err)
    except Exception as e:
        return {"isError": True, "content": [{"type": "text", "text": f"ERROR: {type(e).__name__}: {e}"}]}
    return {"isError": True, "content": [{"type": "text", "text": f"Unknown tool: {name}"}]}


def handle_rpc(msg: dict) -> dict | None:
    """JSON-RPC 2.0 handler for MCP."""
    m = msg.get("method", "")
    rid = msg.get("id")
    if m == "initialize":
        return {"jsonrpc": "2.0", "id": rid, "result": {
            "protocolVersion": "2025-03-26",
            "serverInfo": {"name": "arena-unified-bridge", "version": VERSION},
            "capabilities": {"tools": {"listChanged": False}}}}
    if m == "tools/list":
        return {"jsonrpc": "2.0", "id": rid, "result": {"tools": MCP_TOOLS}}
    if m == "tools/call":
        params = msg.get("params") or {}
        return {"jsonrpc": "2.0", "id": rid, "result": call_tool(params.get("name", ""), params.get("arguments") or {})}
    if m == "notifications/initialized":
        return None
    return {"jsonrpc": "2.0", "id": rid, "error": {"code": -32601, "message": f"Method not found: {m}"}}


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

ROOT_AGENT = Path(os.environ.get("ARENA_AGENT_HOME", str(BRIDGE_DIR))).expanduser()
QUEUE = ROOT_AGENT / "queue"
INBOX = QUEUE / "inbox"
RUNNING = QUEUE / "running"
DONE = QUEUE / "done"
FAILED = QUEUE / "failed"

# Additional directory constants for new endpoints
SKILLS_DIR = ROOT_AGENT / "skills"
HOOKS_DIR = ROOT_AGENT / "hooks"
AGENTS_DIR = ROOT_AGENT / "agents"
SUBAGENTS_DIR = ROOT_AGENT / "subagents"
MEMORY_FILE = ROOT_AGENT / "memory" / "facts.jsonl"
MEMORY_DB = ROOT_AGENT / "memory" / "facts.db"
MISSIONS_DIR = ROOT_AGENT / "missions"
REPORTS_DIR = ROOT_AGENT / "reports"
WEBHOOKS_FILE = ROOT_AGENT / "webhooks.json"
# BACKUPS_DIR removed in v2.5.2 — backup feature deleted


def move_atomic(src: Path, dst: Path) -> None:
    """Atomically move a file, replacing destination if it exists."""
    try:
        if dst.exists():
            dst.unlink()
        src.rename(dst)
    except OSError:
        # Fallback: copy then delete
        import shutil
        shutil.copy2(str(src), str(dst))
        try:
            src.unlink()
        except OSError:
            pass


def task_ensure_dirs():
    for p in [INBOX, RUNNING, DONE, FAILED]:
        p.mkdir(parents=True, exist_ok=True)


async def task_run_one(task_path: Path) -> bool:
    """Process a single task JSON file asynchronously."""
    try:
        task = json.loads(task_path.read_text(encoding="utf-8"))
    except Exception as e:
        log.error("[TaskRunner] Failed to read %s: %s", task_path, e)
        return False

    tid = task.get("id") or task_path.stem
    rp = RUNNING / task_path.name
    try:
        task_path.rename(rp)
    except FileNotFoundError:
        return False

    task["started_at"] = utc_now()
    task["state"] = "running"
    rp.write_text(json.dumps(task, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    cwd = Path(task.get("cwd") or str(Path.home())).expanduser()
    timeout = int(task.get("timeout") or 3600)
    # Apply safety checks (same as /v1/exec)
    blk = blocked_reason(task["cmd"])
    if blk:
        task["state"] = "failed"
        task["exit_code"] = -1
        task["stderr"] = f"blocked: {blk}"
        rp.write_text(json.dumps(task, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        move_atomic(rp, FAILED / rp.name)
        return
    env = os.environ.copy()
    if isinstance(task.get("env"), dict):
        env.update({str(k): str(v) for k, v in task["env"].items()})

    t0 = time.time()
    try:
        proc = await asyncio.create_subprocess_shell(
            task["cmd"], cwd=str(cwd), env=env,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            stdout = stdout.decode("utf-8", "replace")
            stderr = stderr.decode("utf-8", "replace")
            exit_code = proc.returncode
        except asyncio.TimeoutError:
            proc.kill()
            stdout, stderr = "", "timeout"
            exit_code = 124
    except Exception as e:
        stdout, stderr = "", repr(e)
        exit_code = 125

    duration = round(time.time() - t0, 3)
    max_output = int(task.get("max_output") or 2_000_000)
    truncated = False
    if len(stdout.encode("utf-8", "replace")) > max_output:
        stdout = stdout[:max_output]; truncated = True
    if len(stderr.encode("utf-8", "replace")) > max_output:
        stderr = stderr[:max_output]; truncated = True

    state = "done" if exit_code == 0 else "failed"
    task.update({
        "finished_at": utc_now(), "duration_sec": duration,
        "exit_code": exit_code, "stdout": stdout, "stderr": stderr,
        "truncated": truncated, "state": state,
    })
    dest = (DONE if exit_code == 0 else FAILED) / task_path.name
    dest.write_text(json.dumps(task, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    try:
        rp.unlink()
    except FileNotFoundError:
        pass

    log.info("[TaskRunner] %s: %s exit=%s dur=%ss", tid, state, exit_code, duration)
    return True


async def task_runner_loop(app: web.Application):
    """Background task: watches INBOX for new tasks every 5 seconds."""
    task_ensure_dirs()
    log.info("[TaskRunner] Watching %s", INBOX)
    while True:
        try:
            task_ensure_dirs()
            for p in sorted(INBOX.glob("*.json"))[:3]:
                await task_run_one(p)
        except Exception as e:
            log.error("[TaskRunner] Loop error: %s", e)
        # Periodic cleanup of stale MCP sessions
        try:
            removed = _cleanup_mcp_sessions()
            if removed:
                log.info("[TaskRunner] Cleaned %d stale MCP sessions", removed)
        except Exception:
            pass
        await asyncio.sleep(5)


# ============================================================================
# APP CONFIG
# ============================================================================

def make_app(cfg: dict) -> web.Application:
    app = web.Application(client_max_size=50 * 1024 * 1024, middlewares=[error_middleware])
    app["cfg"] = cfg
    app["mcp_sessions"] = {}

    # Store app reference for MCP tool calls that need access to config
    global _app_ref
    _app_ref = app

    # ---- Public endpoints ----
    app.router.add_get("/", handle_index)
    app.router.add_get("/health", handle_health)
    app.router.add_get("/v1/version", handle_v1_version)

    # ---- v1 API (auth required) ----
    app.router.add_get("/v1/info", handle_v1_info)
    app.router.add_get("/v1/status", handle_v1_status)
    app.router.add_get("/v1/sysinfo", handle_v1_sysinfo)
    app.router.add_get("/v1/capabilities", handle_v1_capabilities)
    app.router.add_get("/v1/hardware", handle_v1_hardware)
    app.router.add_get("/v1/hwinfo", handle_v1_hwinfo)  # compatibility alias
    app.router.add_get("/v1/inventory", handle_v1_inventory)
    app.router.add_get("/v1/ps", handle_v1_ps)
    app.router.add_get("/v1/audit", handle_v1_audit)
    app.router.add_post("/v1/exec", handle_v1_exec)
    app.router.add_post("/v1/kill", handle_v1_kill)
    app.router.add_post("/v1/upload", handle_v1_upload)
    app.router.add_get("/v1/download", handle_v1_download)

    # ---- Dashboard API (auth required) ----
    app.router.add_get("/v1/memory", handle_v1_memory)
    app.router.add_post("/v1/memory", handle_v1_memory_set)
    app.router.add_delete("/v1/memory", handle_v1_memory_delete)
    app.router.add_get("/v1/missions", handle_v1_missions)
    app.router.add_post("/v1/beep", handle_v1_beep)
    app.router.add_get("/v1/doctor", handle_v1_doctor)
    app.router.add_get("/v1/reports", handle_v1_reports)
    app.router.add_get("/v1/browser/search", handle_v1_browser_search)
    app.router.add_get("/v1/browser/read", handle_v1_browser_read)

    # ---- v1.5.0 new endpoints ----
    app.router.add_get("/v1/sys/svc", handle_v1_sys_svc)
    app.router.add_get("/v1/service/info", handle_v1_service_info)
    app.router.add_get("/v1/sys/funnel", handle_v1_sys_funnel)
    app.router.add_post("/v1/token/regenerate", handle_v1_token_regenerate)
    app.router.add_post("/v1/tailscale/funnel/{action}", handle_v1_tailscale_funnel)
    app.router.add_get("/v1/tailscale/funnel/{action}", handle_v1_tailscale_funnel)
    app.router.add_post("/v1/cloudflared/tunnel/{action}", handle_v1_cloudflared_tunnel)
    app.router.add_get("/v1/cloudflared/tunnel/{action}", handle_v1_cloudflared_tunnel)
    app.router.add_post("/v1/restart", handle_v1_restart)
    app.router.add_get("/v1/webhooks", handle_v1_webhooks_get)
    app.router.add_post("/v1/webhooks", handle_v1_webhooks_set)
    app.router.add_get("/v1/config", handle_v1_config)
    app.router.add_get("/v1/browser/dump", handle_v1_browser_dump)
    app.router.add_get("/v1/browser/fetch", handle_v1_browser_fetch)
    app.router.add_get("/v1/browser/head", handle_v1_browser_head)

    # ---- CDP (Chrome DevTools Protocol) ----
    app.router.add_get("/v1/browser/cdp/status", handle_v1_cdp_status)
    app.router.add_get("/v1/browser/cdp/diag", handle_v1_cdp_diag)
    app.router.add_get("/v1/browser/cdp/raw-info", handle_v1_cdp_raw_info)
    app.router.add_get("/v1/browser/cdp/test-launch", handle_v1_cdp_test_launch)
    app.router.add_get("/v1/browser/cdp/test-ws", handle_v1_cdp_test_ws)
    app.router.add_post("/v1/browser/cdp/connect", handle_v1_cdp_connect)
    app.router.add_post("/v1/browser/cdp/disconnect", handle_v1_cdp_disconnect)
    app.router.add_post("/v1/browser/cdp/navigate", handle_v1_cdp_navigate)
    app.router.add_get("/v1/browser/cdp/screenshot", handle_v1_cdp_screenshot)
    app.router.add_get("/v1/browser/cdp/dom", handle_v1_cdp_dom)
    app.router.add_post("/v1/browser/cdp/eval", handle_v1_cdp_eval)
    app.router.add_post("/v1/browser/cdp/click", handle_v1_cdp_click)
    app.router.add_post("/v1/browser/cdp/type", handle_v1_cdp_type)
    # Desktop automation (v2.4.0)
    app.router.add_get("/v1/desktop/screenshot", handle_v1_desktop_screenshot)
    app.router.add_post("/v1/desktop/click", handle_v1_desktop_click)
    app.router.add_post("/v1/desktop/type", handle_v1_desktop_type)
    app.router.add_post("/v1/desktop/key", handle_v1_desktop_key)
    app.router.add_post("/v1/desktop/mouse", handle_v1_desktop_mouse)
    app.router.add_get("/v1/desktop/windows", handle_v1_desktop_windows)
    app.router.add_get("/v1/desktop/active_window", handle_v1_desktop_active_window)
    app.router.add_post("/v1/desktop/focus", handle_v1_desktop_focus)
    # Desktop control lease (v2.9.0)
    app.router.add_get("/v1/control/status", handle_v1_control_status)
    app.router.add_post("/v1/control/pause", handle_v1_control_pause)
    app.router.add_post("/v1/control/resume", handle_v1_control_resume)
    app.router.add_post("/v1/control/revoke", handle_v1_control_revoke)
    app.router.add_get("/v1/browser/cdp/tabs", handle_v1_cdp_tabs)
    app.router.add_post("/v1/browser/cdp/tabs/new", handle_v1_cdp_tabs_new)
    app.router.add_post("/v1/browser/cdp/tabs/close", handle_v1_cdp_tabs_close)
    app.router.add_post("/v1/browser/cdp/tabs/activate", handle_v1_cdp_tabs_activate)
    app.router.add_get("/v1/browser/cdp/cookies", handle_v1_cdp_cookies_get)
    app.router.add_post("/v1/browser/cdp/cookies", handle_v1_cdp_cookies_set)
    app.router.add_delete("/v1/browser/cdp/cookies", handle_v1_cdp_cookies_delete)
    app.router.add_post("/v1/browser/cdp/cookies/clear", handle_v1_cdp_cookies_clear)
    app.router.add_get("/v1/browser/cdp/cookies/profiles", handle_v1_cdp_cookies_profiles)
    app.router.add_post("/v1/browser/cdp/cookies/profiles", handle_v1_cdp_cookies_profiles)
    app.router.add_post("/v1/browser/cdp/network/start", handle_v1_cdp_network_start)
    app.router.add_post("/v1/browser/cdp/network/stop", handle_v1_cdp_network_stop)
    app.router.add_get("/v1/browser/cdp/network/requests", handle_v1_cdp_network_requests)
    app.router.add_get("/v1/browser/cdp/network/har", handle_v1_cdp_network_har)
    app.router.add_post("/v1/browser/cdp/intercept/start", handle_v1_cdp_intercept_start)
    app.router.add_post("/v1/browser/cdp/intercept/stop", handle_v1_cdp_intercept_stop)
    app.router.add_post("/v1/browser/cdp/intercept/rule", handle_v1_cdp_intercept_rule)
    app.router.add_delete("/v1/browser/cdp/intercept/rule", handle_v1_cdp_intercept_rule)
    app.router.add_get("/v1/browser/cdp/intercept/rules", handle_v1_cdp_intercept_rule)
    app.router.add_get("/v1/browser/cdp/session/check", handle_v1_cdp_session_check)
    app.router.add_post("/v1/browser/cdp/stealth/extract", handle_v1_cdp_stealth_extract)
    app.router.add_post("/v1/browser/cdp/stealth/shot", handle_v1_cdp_stealth_shot)
    app.router.add_get("/v1/browser/cdp/health", handle_v1_cdp_health)

    # Short CDP aliases for agents/tools that infer paths from docs.
    app.router.add_get("/v1/cdp/status", handle_v1_cdp_status)
    app.router.add_get("/v1/cdp/diag", handle_v1_cdp_diag)
    app.router.add_get("/v1/cdp/raw-info", handle_v1_cdp_raw_info)
    app.router.add_get("/v1/cdp/test-launch", handle_v1_cdp_test_launch)
    app.router.add_get("/v1/cdp/test-ws", handle_v1_cdp_test_ws)
    app.router.add_post("/v1/cdp/connect", handle_v1_cdp_connect)
    app.router.add_post("/v1/cdp/disconnect", handle_v1_cdp_disconnect)
    app.router.add_post("/v1/cdp/navigate", handle_v1_cdp_navigate)
    app.router.add_get("/v1/cdp/screenshot", handle_v1_cdp_screenshot)
    app.router.add_get("/v1/cdp/dom", handle_v1_cdp_dom)
    app.router.add_post("/v1/cdp/eval", handle_v1_cdp_eval)
    app.router.add_post("/v1/cdp/click", handle_v1_cdp_click)
    app.router.add_post("/v1/cdp/type", handle_v1_cdp_type)
    app.router.add_get("/v1/cdp/tabs", handle_v1_cdp_tabs)
    app.router.add_post("/v1/cdp/tabs/new", handle_v1_cdp_tabs_new)
    app.router.add_post("/v1/cdp/tabs/close", handle_v1_cdp_tabs_close)
    app.router.add_post("/v1/cdp/tabs/activate", handle_v1_cdp_tabs_activate)
    app.router.add_get("/v1/cdp/cookies", handle_v1_cdp_cookies_get)
    app.router.add_post("/v1/cdp/cookies", handle_v1_cdp_cookies_set)
    app.router.add_delete("/v1/cdp/cookies", handle_v1_cdp_cookies_delete)
    app.router.add_post("/v1/cdp/cookies/clear", handle_v1_cdp_cookies_clear)
    app.router.add_get("/v1/cdp/cookies/profiles", handle_v1_cdp_cookies_profiles)
    app.router.add_post("/v1/cdp/cookies/profiles", handle_v1_cdp_cookies_profiles)
    app.router.add_post("/v1/cdp/network/start", handle_v1_cdp_network_start)
    app.router.add_post("/v1/cdp/network/stop", handle_v1_cdp_network_stop)
    app.router.add_get("/v1/cdp/network/requests", handle_v1_cdp_network_requests)
    app.router.add_get("/v1/cdp/network/har", handle_v1_cdp_network_har)
    app.router.add_post("/v1/cdp/intercept/start", handle_v1_cdp_intercept_start)
    app.router.add_post("/v1/cdp/intercept/stop", handle_v1_cdp_intercept_stop)
    app.router.add_post("/v1/cdp/intercept/rule", handle_v1_cdp_intercept_rule)
    app.router.add_delete("/v1/cdp/intercept/rule", handle_v1_cdp_intercept_rule)
    app.router.add_get("/v1/cdp/intercept/rules", handle_v1_cdp_intercept_rule)
    app.router.add_get("/v1/cdp/session/check", handle_v1_cdp_session_check)
    app.router.add_post("/v1/cdp/stealth/extract", handle_v1_cdp_stealth_extract)
    app.router.add_post("/v1/cdp/stealth/shot", handle_v1_cdp_stealth_shot)
    app.router.add_get("/v1/cdp/health", handle_v1_cdp_health)

    app.router.add_get("/v1/recall", handle_v1_recall)
    app.router.add_get("/v1/recall/digest", handle_v1_recall_digest)
    app.router.add_get("/v1/audit/stats", handle_v1_audit_stats)
    app.router.add_get("/v1/tasks", handle_v1_tasks_get)
    app.router.add_post("/v1/tasks", handle_v1_tasks_post)
    app.router.add_post("/v1/tasks/clean", handle_v1_tasks_clean)
    app.router.add_get("/v1/skills", handle_v1_skills)
    app.router.add_post("/v1/skills/install", handle_v1_skills_install)
    app.router.add_post("/v1/skills/uninstall", handle_v1_skills_uninstall)
    app.router.add_post("/v1/skills/run", handle_v1_skills_run)
    app.router.add_get("/v1/hooks", handle_v1_hooks)
    app.router.add_get("/v1/agents", handle_v1_agents)
    app.router.add_get("/v1/subagents", handle_v1_subagents)
    app.router.add_post("/v1/subagents/spawn", handle_v1_subagents_spawn)
    app.router.add_get("/v1/mission/show", handle_v1_mission_show)
    app.router.add_get("/v1/metrics", handle_v1_metrics)
    app.router.add_get("/v1/logs", handle_v1_logs)

    # ---- Prometheus & API docs (public) ----
    app.router.add_get("/metrics", handle_prometheus_metrics)
    app.router.add_get("/api-docs", handle_api_docs)
    app.router.add_get("/openapi.json", handle_api_docs)  # v2.10.0 alias

    # ---- Browser auto-switch ----
    app.router.add_post("/v1/browser/browse", handle_v1_browser_browse)

    # ---- Phase 3: WebSocket events ----
    app.router.add_get("/v1/events", handle_v1_events)

    # ---- Phase 3: Skills hot-reload ----
    app.router.add_post("/v1/skills/reload", handle_v1_skills_reload)

    # ---- Phase 3: Request/response log ----
    app.router.add_get("/v1/audit/log", handle_v1_audit_log)

    # ---- Phase 3: Watchdog ----
    app.router.add_get("/v1/watchdog", handle_v1_watchdog)
    app.router.add_post("/v1/watchdog", handle_v1_watchdog)

    # ---- Phase 3: Multi-user auth ----
    app.router.add_get("/v1/users", handle_v1_users)
    app.router.add_post("/v1/users", handle_v1_users)
    app.router.add_delete("/v1/users", handle_v1_users)

    # ---- Phase 3: Batch operations ----
    app.router.add_post("/v1/batch", handle_v1_batch)

    # ---- Phase 3: Browser session profiles ----
    app.router.add_get("/v1/profiles", handle_v1_profiles)
    app.router.add_post("/v1/profiles", handle_v1_profiles)
    app.router.add_post("/v1/profiles/{name}/load", handle_v1_profiles_load)

    # ---- Phase 3: Prometheus alerts ----
    app.router.add_get("/v1/alerts", handle_v1_alerts)
    app.router.add_post("/v1/alerts", handle_v1_alerts)

    # ---- Phase 4: Built-in TLS/HTTPS ----
    app.router.add_get("/v1/tls", handle_v1_tls)
    app.router.add_post("/v1/tls", handle_v1_tls)

    # ---- Phase 4: gRPC-style secondary interface ----
    app.router.add_get("/v1/grpc", handle_v1_grpc)
    app.router.add_post("/v1/grpc", handle_v1_grpc)

    # ---- Phase 4: Live Dashboard v2 ----
    app.router.add_get("/gui/v2", handle_gui_v2)

    # ---- Phase 4: Rate Limiting v2 ----
    app.router.add_get("/v1/ratelimit", handle_v1_ratelimit)
    app.router.add_post("/v1/ratelimit", handle_v1_ratelimit)

    # ---- Phase 4: Skill Sandboxing ----
    app.router.add_get("/v1/sandbox", handle_v1_sandbox)
    app.router.add_post("/v1/sandbox", handle_v1_sandbox)

    # ---- Phase 4: Clustering/HA ----
    app.router.add_get("/v1/cluster", handle_v1_cluster)
    app.router.add_post("/v1/cluster", handle_v1_cluster)

    # ---- Phase 4: API Versioning (/v2/) ----
    app.router.add_get("/v2/", handle_v2_index)
    app.router.add_get("/v2/status", handle_v2_status)
    app.router.add_get("/v2/health", handle_v2_health)
    app.router.add_get("/v2/browser/status", handle_v2_browser_status)
    app.router.add_post("/v2/exec", handle_v2_exec)
    app.router.add_get("/v2/deprecations", handle_v2_deprecations)

    # ---- Phase 4: OpenTelemetry Tracing ----
    app.router.add_get("/v1/tracing", handle_v1_tracing)
    app.router.add_post("/v1/tracing", handle_v1_tracing)
    app.router.add_get("/v1/traces/export", handle_v1_traces_export)
    app.router.add_post("/v1/traces/export", handle_v1_traces_export)

    # ---- Dashboard ----
    app.router.add_get("/gui", handle_gui)

    # ---- MCP Streamable HTTP ----
    app.router.add_post("/mcp", handle_mcp_post)
    app.router.add_delete("/mcp", handle_mcp_delete)

    # ---- MCP SSE Legacy ----
    app.router.add_get("/sse", handle_sse)
    app.router.add_post("/messages", handle_sse_messages)

    # ---- MCP WebSocket ----
    app.router.add_get("/ws", handle_ws)

    # ---- Web Gateway ----
    app.router.add_get("/gateway", handle_gateway_index)
    app.router.add_get("/gateway/tools", handle_gateway_tools)
    app.router.add_post("/run", handle_gateway_run)
    app.router.add_post("/tool", handle_gateway_tool)

    # ---- Background tasks ----
    app.on_startup.append(on_startup)
    app.on_cleanup.append(on_cleanup)

    return app


async def on_startup(app: web.Application):
    """Start background task runner and initialize async primitives."""
    # Initialize Memory DB (non-blocking)
    await asyncio.get_event_loop().run_in_executor(_EXECUTOR, init_memory_db)
    
    cfg = app["cfg"]
    cfg["semaphore"] = asyncio.Semaphore(cfg["max_concurrent"])
    app["task_runner"] = asyncio.ensure_future(task_runner_loop(app))
    # v2.1.0: Start log cleanup + disk monitor
    app["log_cleanup"] = asyncio.ensure_future(_log_cleanup_loop(app))
    # Phase 3: Start health watchdog
    _start_watchdog()
    # v2.4.0: Auto-start ydotoold for Wayland desktop automation
    if shutil.which("ydotoold") and not os.path.exists("/run/user/%d/.ydotool_socket" % os.getuid()):
        try:
            proc = await asyncio.create_subprocess_exec(
                "ydotoold",
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            log.info("[Desktop] ydotoold started (PID %d) for Wayland automation", proc.pid)
        except Exception as e:
            log.debug("[Desktop] Could not start ydotoold (non-fatal): %s", e)
    log.info("[UnifiedBridge v%s] Background task runner + watchdog + log cleanup started", VERSION)


async def on_cleanup(app: web.Application):
    """Stop background task runner and clean up resources."""
    tr = app.get("task_runner")
    if tr:
        tr.cancel()
        try:
            await tr
        except asyncio.CancelledError:
            pass
    # v2.1.0: Stop log cleanup
    lc = app.get("log_cleanup")
    if lc:
        lc.cancel()
        try:
            await lc
        except asyncio.CancelledError:
            pass

    # Phase 3: Stop health watchdog
    try:
        _stop_watchdog()
    except Exception:
        pass
    
    # Stop CDP watcher
    try:
        _stop_cdp_watcher()
    except Exception:
        pass
    
    # Close CDP connection
    try:
        if _cdp_state.get("manager"):
            await asyncio.wait_for(_cdp_state["manager"].close(), timeout=10)
    except Exception:
        pass
    
    # Stop gRPC server task
    await stop_grpc_server()
    
    # Stop cluster heartbeat task
    await stop_cluster_heartbeat()

    # Shutdown thread pool executors
    _EXECUTOR.shutdown(wait=False)
    _SLOW_EXECUTOR.shutdown(wait=False)


# ============================================================================
# AUTH HELPER
# ============================================================================

def check_auth(request: web.Request) -> bool:
    cfg = request.app["cfg"]
    token = cfg["token"]
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer ") and hmac.compare_digest(auth[7:], token):
        return True
    # Also check X-Arena-Token for gateway compat
    xt = request.headers.get("X-Arena-Token", "")
    if xt and hmac.compare_digest(xt, token):
        return True
    # v2.1.1: Also check multi-user tokens from users.json
    is_authed, _ = check_auth_with_role(request)
    if is_authed:
        return True
    return False


def require_auth(request: web.Request) -> web.Response | None:
    """Returns None if auth OK, or a 401 Response if not.
    
    Includes auth-specific rate limiting: 10 failed attempts per minute per IP.
    """
    if check_auth(request):
        return None
    # Auth-specific rate limiting (v2.1.1)
    peer = request.remote or "unknown"
    now = time.time()
    with _rate_limit_lock:
        key = f"auth_fail:{peer}"
        if key not in _rate_limit_store:
            _rate_limit_store[key] = []
        # Remove entries older than 60 seconds
        _rate_limit_store[key] = [t for t in _rate_limit_store[key] if now - t < 60]
        if len(_rate_limit_store[key]) >= 10:
            log.warning("[Auth-RateLimit] IP %s has %d failed auth attempts in 60s", peer, len(_rate_limit_store[key]))
            return _cors_json_response(
                {"ok": False, "error": "too many failed auth attempts, try again later"},
                status=429,
                extra_headers={"Retry-After": "60"}
            )
        _rate_limit_store[key].append(now)
    return _cors_json_response({"ok": False, "error": "unauthorized"}, status=401)


_gateway_handler_ctx = GatewayHandlerContext(
    require_auth=require_auth,
    record_request=_record_request,
    cors_json_response=_cors_json_response,
    executor=_EXECUTOR,
    handle_rpc=handle_rpc,
    subprocess_kwargs=_subprocess_kwargs,
)
_gateway_handlers = make_gateway_handlers(_gateway_handler_ctx)
handle_gateway_index = _gateway_handlers.index
handle_gateway_tools = _gateway_handlers.tools
handle_gateway_run = _gateway_handlers.run
handle_gateway_tool = _gateway_handlers.tool


_mcp_handler_ctx = McpHandlerContext(
    require_auth=require_auth,
    record_request=_record_request,
    cors_json_response=_cors_json_response,
    handle_rpc=handle_rpc,
    log_error=log.error,
)
_mcp_handlers = make_mcp_handlers(_mcp_handler_ctx)
handle_mcp_post = _mcp_handlers.mcp_post
handle_mcp_delete = _mcp_handlers.mcp_delete
handle_sse = _mcp_handlers.sse
handle_sse_messages = _mcp_handlers.sse_messages
handle_ws = _mcp_handlers.ws


_api_v2_handler_ctx = ApiV2HandlerContext(
    require_auth=require_auth,
    record_request=_record_request,
    cors_json_response=_cors_json_response,
    version=VERSION,
    metrics=BRIDGE_METRICS,
    cdp_state=_cdp_state,
    watchdog_state=_watchdog_state,
    cluster_state=_cluster_state,
    cluster_config=_cluster_config,
    tls_config=_tls_config,
    profiles_dir=_PROFILES_DIR,
    sandbox_config=_sandbox_config,
    blocked_reason=blocked_reason,
    first_word=first_word,
    decode_output=decode_output,
    run_sandboxed=_run_sandboxed,
    cfg_get_max_timeout=cfg_get_max_timeout,
    audit=audit,
    emit_event=emit_event,
    now=time.time,
)
_api_v2_handlers = make_v2_handlers(_api_v2_handler_ctx)
handle_v2_index = _api_v2_handlers.index
handle_v2_status = _api_v2_handlers.status
handle_v2_health = _api_v2_handlers.health
handle_v2_browser_status = _api_v2_handlers.browser_status
handle_v2_exec = _api_v2_handlers.exec
handle_v2_deprecations = _api_v2_handlers.deprecations


_batch_handler_ctx = BatchHandlerContext(
    require_auth=require_auth,
    record_request=_record_request,
    cors_json_response=_cors_json_response,
    emit_event=emit_event,
    now=time.time,
)
_batch_handlers = make_batch_handlers(_batch_handler_ctx)
handle_v1_batch = _batch_handlers.batch


_alert_handler_ctx = AlertsHandlerContext(
    require_auth=require_auth,
    record_request=_record_request,
    cors_json_response=_cors_json_response,
    metrics=BRIDGE_METRICS,
    watchdog_state=_watchdog_state,
    cdp_state=_cdp_state,
    rate_limit_lock=_rate_limit_lock,
    rate_limit_store=_rate_limit_store,
    rate_limit_window=_rate_limit_window,
    rate_limit_max=_rate_limit_max,
    now=time.time,
    log_info=log.info,
)
_alert_handlers = make_alert_handlers(_alert_handler_ctx)
handle_v1_alerts = _alert_handlers.alerts


_rate_limit_handler_ctx = RateLimitHandlerContext(
    require_auth=require_auth,
    record_request=_record_request,
    cors_json_response=_cors_json_response,
    update_rate_limit_config=update_rate_limit_config,
    rate_limit_stats=rate_limit_stats,
    log_info=log.info,
)
_rate_limit_handlers = make_rate_limit_handlers(_rate_limit_handler_ctx)
handle_v1_ratelimit = _rate_limit_handlers.ratelimit


_tls_handler_ctx = TlsHandlerContext(
    require_auth=require_auth,
    record_request=_record_request,
    cors_json_response=_cors_json_response,
    generate_self_signed_cert=_generate_self_signed_cert,
    get_tailscale_cert=_get_tailscale_cert,
    log_info=log.info,
)
_tls_handlers = make_tls_handlers(_tls_handler_ctx)
handle_v1_tls = _tls_handlers.tls


_sandbox_handler_ctx = SandboxHandlerContext(
    require_auth=require_auth,
    record_request=_record_request,
    cors_json_response=_cors_json_response,
    blocked_reason=blocked_reason,
    first_word=first_word,
    run_sandboxed=_run_sandboxed,
    audit=audit,
    emit_event=emit_event,
)
_sandbox_handlers = make_sandbox_handlers(_sandbox_handler_ctx)
handle_v1_sandbox = _sandbox_handlers.sandbox


_cluster_handler_ctx = ClusterHandlerContext(
    require_auth=require_auth,
    record_request=_record_request,
    cors_json_response=_cors_json_response,
    get_node_id=_get_node_id,
    start_heartbeat=lambda: start_cluster_heartbeat(log_error=log.error),
    stop_heartbeat=stop_cluster_heartbeat,
    audit=audit,
    log_info=log.info,
)
_cluster_handlers = make_cluster_handlers(_cluster_handler_ctx)
handle_v1_cluster = _cluster_handlers.cluster


_profile_handler_ctx = ProfileHandlerContext(
    require_auth=require_auth,
    record_request=_record_request,
    cors_json_response=_cors_json_response,
    profiles_dir=_PROFILES_DIR,
    ensure_profiles_dir=_ensure_profiles_dir,
    cdp_state=_cdp_state,
    cdp_active_tab=lambda *args, **kwargs: _cdp_active_tab(*args, **kwargs),
    version=VERSION,
    utc_now=utc_now,
    audit=audit,
    emit_event=emit_event,
    log_warning=log.warning,
)
_profile_handlers = make_profile_handlers(_profile_handler_ctx)
handle_v1_profiles = _profile_handlers.profiles
handle_v1_profiles_load = _profile_handlers.load


_grpc_handler_ctx = GrpcHandlerContext(
    require_auth=require_auth,
    record_request=_record_request,
    cors_json_response=_cors_json_response,
    server_task=_grpc_server_task,
    start_server=lambda cfg: start_grpc_server(cfg, log_info=log.info, log_error=log.error),
    stop_server=stop_grpc_server,
)
_grpc_handlers = make_grpc_handlers(_grpc_handler_ctx)
handle_v1_grpc = _grpc_handlers.grpc


_event_handler_ctx = EventHandlerContext(
    require_auth=require_auth,
    version=VERSION,
    utc_now=utc_now,
    log_info=log.info,
)
_event_handlers = make_event_handlers(_event_handler_ctx)
handle_v1_events = _event_handlers.events


_watchdog_handler_ctx = WatchdogHandlerContext(
    require_auth=require_auth,
    record_request=_record_request,
    cors_json_response=_cors_json_response,
    metrics=BRIDGE_METRICS,
    now=time.time,
    log_info=log.info,
)
_watchdog_handlers = make_watchdog_handlers(_watchdog_handler_ctx)
handle_v1_watchdog = _watchdog_handlers.watchdog


_gui_handler_ctx = GuiHandlerContext(
    cors_json_response=_cors_json_response,
    bridge_dir=BRIDGE_DIR,
    version=VERSION,
)
_gui_handlers = make_gui_handlers(_gui_handler_ctx)
handle_gui = _gui_handlers.gui
handle_gui_v2 = _gui_handlers.gui_v2


_runtime_observability_handler_ctx = RuntimeObservabilityHandlerContext(
    require_auth=require_auth,
    record_request=_record_request,
    cors_json_response=_cors_json_response,
    metrics=BRIDGE_METRICS,
    metrics_lock=_metrics_lock,
    active_processes=ACTIVE_PROCESSES,
    cdp_state=_cdp_state,
    watchdog_state=_watchdog_state,
    event_subscribers=_event_subscribers,
    tls_config=_tls_config,
    grpc_config=_grpc_config,
    cluster_state=_cluster_state,
    sandbox_config=_sandbox_config,
    otel_config=_otel_config,
    log_file=LOG_FILE,
    version=VERSION,
    now=time.time,
    log_error=log.error,
)
_runtime_observability_handlers = make_runtime_observability_handlers(_runtime_observability_handler_ctx)
handle_v1_metrics = _runtime_observability_handlers.metrics
handle_prometheus_metrics = _runtime_observability_handlers.prometheus_metrics
handle_v1_logs = _runtime_observability_handlers.logs


_tracing_handler_ctx = TracingHandlerContext(
    require_auth=require_auth,
    record_request=_record_request,
    cors_json_response=_cors_json_response,
    version=VERSION,
    log_info=log.info,
)
_tracing_handlers = make_tracing_handlers(_tracing_handler_ctx)
handle_v1_tracing = _tracing_handlers.tracing
handle_v1_traces_export = _tracing_handlers.traces_export


_user_handler_ctx = UserHandlerContext(
    require_auth=require_auth,
    record_request=_record_request,
    cors_json_response=_cors_json_response,
    check_auth_with_role=check_auth_with_role,
    list_users=_user_store.list_users_for_response,
    add_or_update_user=_user_store.add_or_update_user,
    remove_user=_user_store.remove_user,
    token_generator=b64_token,
    audit=audit,
    log_info=log.info,
)
_user_handlers = make_user_handlers(_user_handler_ctx)
handle_v1_users = _user_handlers.users


_file_handler_ctx = FileHandlerContext(
    require_auth=require_auth,
    record_request=_record_request,
    cors_json_response=_cors_json_response,
    audit=audit,
    home=Path.home(),
    bridge_py=Path(__file__).resolve(),
)
_file_handlers = make_file_handlers(_file_handler_ctx)
handle_v1_upload = _file_handlers.upload
handle_v1_download = _file_handlers.download

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


_system_handler_ctx = SystemHandlerContext(
    require_auth=require_auth,
    record_request=_record_request,
    cors_json_response=_cors_json_response,
    executor=_EXECUTOR,
    common_status=common_status,
    version=VERSION,
    clean_platform_name=get_clean_platform_name,
    doctor_sync=_doctor_sync,
    sysinfo_sync=_sysinfo_sync,
    play_beep_sync=_play_beep_sync,
)
_system_handlers = make_system_handlers(_system_handler_ctx)
handle_v1_version = _system_handlers.version
handle_v1_info = _system_handlers.info
handle_v1_status = _system_handlers.status
handle_v1_config = _system_handlers.config
handle_v1_doctor = _system_handlers.doctor
handle_v1_sysinfo = _system_handlers.sysinfo
handle_v1_beep = _system_handlers.beep


_admin_handler_ctx = AdminHandlerContext(
    require_auth=require_auth,
    record_request=_record_request,
    cors_json_response=_cors_json_response,
    executor=_EXECUTOR,
    audit=audit,
    default_token_file=TOKEN_FILE,
    root_agent=ROOT_AGENT,
    subprocess_kwargs=_subprocess_kwargs,
)
_admin_handlers = make_admin_handlers(_admin_handler_ctx)
handle_v1_sys_funnel = _admin_handlers.sys_funnel
handle_v1_token_regenerate = _admin_handlers.token_regenerate
handle_v1_tailscale_funnel = _admin_handlers.tailscale_funnel
handle_v1_cloudflared_tunnel = _admin_handlers.cloudflared_tunnel


_public_handler_ctx = PublicHandlerContext(
    record_request=_record_request,
    cors_json_response=_cors_json_response,
    metrics=BRIDGE_METRICS,
    version=VERSION,
    now=time.time,
    hostname=socket.gethostname,
    bridge_port=_get_bridge_port,
)
_public_handlers = make_public_handlers(_public_handler_ctx)
handle_index = _public_handlers.index
handle_health = _public_handlers.health
handle_api_docs = _public_handlers.api_docs


# ============================================================================
# HANDLERS — Public
# ============================================================================
# Public index and health handlers now live in arena/public/handlers.py.



def _hwinfo_sync():
    """Collect extended hardware info. Cross-platform."""
    import subprocess, platform
    import re as _re
    info = {
        "os": {
            "system": platform.system(),
            "release": platform.release(),
            "version": platform.version(),
            "machine": platform.machine(),
            "node": platform.node(),
        },
        "motherboard": None,
        "bios": None,
        "cpu": None,
        "gpu": None,
        "gpus": [],
        "ram_total_gb": None,
        "ram_used_gb": None,
        "ram_avail_gb": None,
        "ram_modules": [],
        "disks": [],
    }

    def _run(cmd, timeout=8):
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, **_subprocess_kwargs())
            return r.stdout if r.returncode == 0 else ""
        except (subprocess.TimeoutExpired, Exception):
            return ""

    if platform.system() == "Windows":
        def get_cim_json(class_name, properties):
            cmd = ["powershell", "-NoProfile", "-NonInteractive", "-Command", 
                   f"Get-CimInstance {class_name} | Select-Object {properties} | ConvertTo-Json -Compress"]
            try:
                out = _run(cmd, timeout=10)
                if not out or not out.strip():
                    return []
                data = json.loads(out.strip())
                if isinstance(data, dict):
                    return [data]
                if isinstance(data, list):
                    return data
            except Exception:
                pass
            return []

        # Motherboard
        mb_blocks = get_cim_json("Win32_BaseBoard", "Manufacturer,Product,Version")
        if mb_blocks and mb_blocks[0].get("Manufacturer"):
            d = mb_blocks[0]
            info["motherboard"] = {
                "manufacturer": str(d.get("Manufacturer") or ""),
                "product": str(d.get("Product") or ""),
                "version": str(d.get("Version") or ""),
            }
        # BIOS
        bios_blocks = get_cim_json("Win32_BIOS", "SMBIOSBIOSVersion,Manufacturer,ReleaseDate")
        if bios_blocks and bios_blocks[0].get("SMBIOSBIOSVersion"):
            d = bios_blocks[0]
            # ReleaseDate from CIM might be a dict like {'value': '...', 'DateTime': '...'} or string
            # We'll just cast to string and take first 8 chars if it matches YYYYMMDD
            rd = str(d.get("ReleaseDate") or "")
            if isinstance(d.get("ReleaseDate"), dict) and "DateTime" in d["ReleaseDate"]:
                rd = str(d["ReleaseDate"]["DateTime"])
            info["bios"] = {
                "version": str(d.get("SMBIOSBIOSVersion") or ""),
                "manufacturer": str(d.get("Manufacturer") or ""),
                "release_date": rd[:8] if len(rd) >= 8 else rd,
            }
        # CPU
        cpu_blocks = get_cim_json("Win32_Processor", "Name,NumberOfCores,NumberOfLogicalProcessors,MaxClockSpeed")
        if cpu_blocks and cpu_blocks[0].get("Name"):
            d = cpu_blocks[0]
            try: cores = int(d.get("NumberOfCores") or 0)
            except Exception: cores = 0
            try: threads = int(d.get("NumberOfLogicalProcessors") or 0)
            except Exception: threads = 0
            try: ghz = round(int(d.get("MaxClockSpeed") or 0) / 1000.0, 2)
            except Exception: ghz = 0
            info["cpu"] = {"name": str(d.get("Name") or ""), "cores": cores, "threads": threads, "max_ghz": ghz}
        # GPU
        gpu_blocks = get_cim_json("Win32_VideoController", "Name,AdapterRAM")
        for d in gpu_blocks:
            if d.get("Name"):
                try: vram_mb = int(d.get("AdapterRAM") or 0) // (1024 * 1024)
                except Exception: vram_mb = 0
                info["gpus"].append({"name": str(d.get("Name") or ""), "vram_mb": vram_mb})
        if info["gpus"]:
            info["gpu"] = info["gpus"][0]
        # RAM modules
        ram_blocks = get_cim_json("Win32_PhysicalMemory", "Capacity,Speed,Manufacturer,PartNumber")
        total_bytes = 0
        for d in ram_blocks:
            if d.get("Capacity"):
                try:
                    cap = int(d["Capacity"])
                    total_bytes += cap
                    info["ram_modules"].append({
                        "size_gb": round(cap / (1024 ** 3), 1),
                        "speed_mhz": int(d.get("Speed") or 0),
                        "manufacturer": str(d.get("Manufacturer") or "").strip(),
                        "part_number": str(d.get("PartNumber") or "").strip(),
                    })
                except Exception:
                    pass
        if total_bytes:
            info["ram_total_gb"] = round(total_bytes / (1024 ** 3), 1)
        # Disks
        disk_blocks = get_cim_json("Win32_LogicalDisk", "DeviceID,Size,FreeSpace,FileSystem,VolumeName")
        for d in disk_blocks:
            if d.get("DeviceID") and d.get("Size"):
                try:
                    size = int(d["Size"])
                    free = int(d.get("FreeSpace") or 0)
                    info["disks"].append({
                        "device": str(d.get("DeviceID") or ""),
                        "volume": str(d.get("VolumeName") or "").strip(),
                        "filesystem": str(d.get("FileSystem") or "").strip(),
                        "total_gb": round(size / (1024 ** 3), 1),
                        "free_gb": round(free / (1024 ** 3), 1),
                        "used_pct": round((size - free) / size * 100, 1) if size else 0,
                    })
                except Exception:
                    pass

    elif platform.system() == "Linux":
        # CPU via /proc/cpuinfo
        try:
            with open("/proc/cpuinfo") as f:
                cpuinfo = f.read()
            mname = _re.search(r"model name\s*:\s*(.+)", cpuinfo)
            ncpus = len(_re.findall(r"^processor\s*:", cpuinfo, _re.M))
            ncores_set = set(_re.findall(r"core id\s*:\s*(\d+)", cpuinfo))
            info["cpu"] = {
                "name": mname.group(1).strip() if mname else "Unknown",
                "cores": len(ncores_set) or ncpus,
                "threads": ncpus,
                "max_ghz": 0,
            }
        except Exception:
            pass
        # RAM via /proc/meminfo
        try:
            with open("/proc/meminfo") as f:
                m = f.read()
            mt = _re.search(r"MemTotal:\s+(\d+)", m)
            ma = _re.search(r"MemAvailable:\s+(\d+)", m)
            if mt:
                total = int(mt.group(1)) * 1024
                avail = int(ma.group(1)) * 1024 if ma else 0
                info["ram_total_gb"] = round(total / (1024 ** 3), 1)
                info["ram_avail_gb"] = round(avail / (1024 ** 3), 1)
                info["ram_used_gb"] = round((total - avail) / (1024 ** 3), 1)
        except Exception:
            pass
        # Motherboard via dmidecode (usually requires root)
        dmi = _run(["dmidecode", "-t", "baseboard"], timeout=5)
        if dmi:
            mfg = _re.search(r"Manufacturer:\s*(.+)", dmi)
            prod = _re.search(r"Product Name:\s*(.+)", dmi)
            if mfg or prod:
                info["motherboard"] = {
                    "manufacturer": (mfg.group(1).strip() if mfg else ""),
                    "product": (prod.group(1).strip() if prod else ""),
                    "version": "",
                }
        # GPU via lspci
        lspci = _run(["lspci"], timeout=5)
        gpu_match = _re.search(r"VGA compatible controller:\s*(.+)", lspci)
        if gpu_match:
            info["gpu"] = {"name": gpu_match.group(1).strip(), "vram_mb": 0}
            info["gpus"].append(info["gpu"])
        # Disks via df
        df = _run(["df", "-B1", "--output=source,target,fstype,size,avail"], timeout=5)
        for line in df.splitlines()[1:]:
            parts = line.split()
            if len(parts) >= 5 and parts[0].startswith("/"):
                try:
                    size = int(parts[3])
                    avail = int(parts[4])
                    if size < 1024 ** 3:
                        continue
                    info["disks"].append({
                        "device": parts[0],
                        "volume": parts[1],
                        "filesystem": parts[2],
                        "total_gb": round(size / (1024 ** 3), 1),
                        "free_gb": round(avail / (1024 ** 3), 1),
                        "used_pct": round((size - avail) / size * 100, 1) if size else 0,
                    })
                except Exception:
                    continue

    return info


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
handle_v1_inventory = _hardware_handlers.inventory
handle_v1_hardware = _hardware_handlers.hardware
handle_v1_hwinfo = _hardware_handlers.hwinfo


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
handle_v1_ps = _exec_handlers.ps
handle_v1_exec = _exec_handlers.exec
handle_v1_kill = _exec_handlers.kill






















# ============================================================================
# HANDLER — Dashboard GUI
# ============================================================================
# Dashboard GUI templates/handlers now live in arena/gui/handlers.py.


# ============================================================================
# HANDLERS — Dashboard API endpoints
# ============================================================================

def init_memory_db():
    return memory_init_db(db_path=MEMORY_DB, jsonl_path=MEMORY_FILE, log_error=log.error)


def _load_facts() -> list[dict]:
    return memory_load_facts(MEMORY_DB)

def _search_facts_paged(q: str = "", offset: int = 0, limit: int = 100) -> tuple[int, list[dict]]:
    return memory_search_facts_paged(MEMORY_DB, q=q, offset=offset, limit=limit, log_error=log.error)


def _write_fact(entry: dict) -> None:
    return memory_write_fact(MEMORY_DB, entry)


def _delete_fact(key: str) -> bool:
    return memory_delete_fact(MEMORY_DB, key)








def _list_missions_sync() -> list[dict]:
    return list_missions(MISSIONS_DIR)


















def _list_reports_sync() -> list[dict]:
    return list_reports(REPORTS_DIR)




def _browser_search_sync(query: str, n: int) -> dict:
    return browser_search(query, n, version=VERSION)




# _validate_url now lives in arena/security.py (re-exported above).


def _browser_read_sync(url: str) -> dict:
    return browser_read(url, version=VERSION, validate_url=_validate_url)




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


_service_handler_ctx = ServiceHandlerContext(
    require_auth=require_auth,
    record_request=_record_request,
    cors_json_response=_cors_json_response,
    executor=_EXECUTOR,
    service_info_sync=_service_info_sync,
    sys_svc_sync=_sys_svc_sync,
    capabilities_sync=_capabilities_sync,
    spawn_respawn_helper=_spawn_respawn_helper,
    audit=audit,
)
_service_handlers = make_service_handlers(_service_handler_ctx)
handle_v1_service_info = _service_handlers.service_info
handle_v1_sys_svc = _service_handlers.sys_svc
handle_v1_capabilities = _service_handlers.capabilities
handle_v1_restart = _service_handlers.restart




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







# --- /v1/browser/dump GET — Full page dump with links ---

def _browser_dump_sync(url: str) -> dict:
    return browser_dump(url, version=VERSION, validate_url=_validate_url)




# --- /v1/browser/fetch GET — Raw content fetch ---

def _browser_fetch_sync(url: str) -> dict:
    return browser_fetch(url, version=VERSION, validate_url=_validate_url)




# --- /v1/browser/head GET — HTTP HEAD ---

def _browser_head_sync(url: str) -> dict:
    return browser_head(url, version=VERSION, validate_url=_validate_url)


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
handle_v1_browser_search = _browser_fetch_handlers.search
handle_v1_browser_read = _browser_fetch_handlers.read
handle_v1_browser_dump = _browser_fetch_handlers.dump
handle_v1_browser_fetch = _browser_fetch_handlers.fetch
handle_v1_browser_head = _browser_fetch_handlers.head


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
handle_v1_browser_browse = _browser_browse_handlers.browse


def _cdp_watcher_active() -> bool:
    return _cdp_watcher_task is not None and not _cdp_watcher_task.done()


_cdp_basic_handler_ctx = CdpBasicHandlerContext(
    require_auth=require_auth,
    record_request=_record_request,
    cors_json_response=_cors_json_response,
    cdp_state=_cdp_state,
    get_cdp_module=_get_cdp_module,
    watcher_active=_cdp_watcher_active,
)
_cdp_basic_handlers = make_cdp_basic_handlers(_cdp_basic_handler_ctx)
handle_v1_cdp_status = _cdp_basic_handlers.status
handle_v1_cdp_diag = _cdp_basic_handlers.diag


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
handle_v1_cdp_raw_info = _cdp_diagnostic_handlers.raw_info
handle_v1_cdp_test_launch = _cdp_diagnostic_handlers.test_launch
handle_v1_cdp_test_ws = _cdp_diagnostic_handlers.test_ws


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
handle_v1_cdp_connect = _cdp_session_handlers.connect
handle_v1_cdp_disconnect = _cdp_session_handlers.disconnect





# ============================================================================
# HANDLERS — CDP (Chrome DevTools Protocol)
# ============================================================================

async def _cdp_active_tab(tab_id: Optional[str] = None):
    """Get a CDPTab instance for the given tab_id or the active tab.
    
    Returns (CDPTab, error_response) tuple. If error_response is not None,
    the handler should return it immediately.
    """
    cdp = _get_cdp_module()
    if not cdp:
        return None, _cors_json_response(
            {"ok": False, "error": "cdp_browser module not found. Install to scripts/ directory."},
            status=500
        )
    
    mgr = _cdp_state.get("manager")
    if not mgr or not _cdp_state["connected"]:
        return None, _cors_json_response(
            {"ok": False, "error": "CDP not connected. POST /v1/browser/cdp/connect first."},
            status=400
        )
    
    if tab_id:
        tab = mgr.get_tab(tab_id)
        if not tab:
            return None, _cors_json_response(
                {"ok": False, "error": f"Tab {tab_id} not found"},
                status=404
            )
        if not tab.connected:
            return None, _cors_json_response(
                {"ok": False, "error": f"Tab {tab_id} is not connected"},
                status=400
            )
        return tab, None
    
    # Use active tab
    tab = mgr.active_tab
    if not tab:
        return None, _cors_json_response(
            {"ok": False, "error": "No active tab. Open a tab first."},
            status=400
        )
    if not tab.connected:
        # Try auto-reconnecting the active tab
        try:
            await tab.connect()
        except Exception as e:
            log.warning("[CDP] Auto-reconnect failed for tab %s: %s", tab.target_id, e)
        if not tab.connected:
            return None, _cors_json_response(
                {"ok": False, "error": "Active tab is not connected and auto-reconnect failed. Try POST /v1/browser/cdp/connect again."},
                status=400
            )
    return tab, None


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
handle_v1_cdp_navigate = _cdp_page_handlers.navigate
handle_v1_cdp_screenshot = _cdp_page_handlers.screenshot
handle_v1_cdp_dom = _cdp_page_handlers.dom
handle_v1_cdp_eval = _cdp_page_handlers.eval
handle_v1_cdp_click = _cdp_page_handlers.click
handle_v1_cdp_type = _cdp_page_handlers.type


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
handle_v1_desktop_screenshot = _desktop_handlers.screenshot
handle_v1_desktop_click = _desktop_handlers.click
handle_v1_desktop_type = _desktop_handlers.type
handle_v1_desktop_key = _desktop_handlers.key
handle_v1_desktop_mouse = _desktop_handlers.mouse
handle_v1_desktop_windows = _desktop_handlers.windows
handle_v1_desktop_active_window = _desktop_handlers.active_window
handle_v1_desktop_focus = _desktop_handlers.focus


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
handle_v1_control_status = _control_lease_handlers.status
handle_v1_control_pause = _control_lease_handlers.pause
handle_v1_control_resume = _control_lease_handlers.resume
handle_v1_control_revoke = _control_lease_handlers.revoke

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
handle_v1_cdp_tabs = _cdp_tabs_handlers.tabs
handle_v1_cdp_tabs_new = _cdp_tabs_handlers.new
handle_v1_cdp_tabs_close = _cdp_tabs_handlers.close
handle_v1_cdp_tabs_activate = _cdp_tabs_handlers.activate


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
handle_v1_cdp_cookies_get = _cdp_cookies_handlers.get
handle_v1_cdp_cookies_set = _cdp_cookies_handlers.set
handle_v1_cdp_cookies_delete = _cdp_cookies_handlers.delete
handle_v1_cdp_cookies_clear = _cdp_cookies_handlers.clear
handle_v1_cdp_cookies_profiles = _cdp_cookies_handlers.profiles


# ---- CDP Cookie Management ----
# Implementations moved to arena/browser/cdp/cookies.py and are bound above via
# make_cdp_cookies_handlers(...).

async def _ensure_cookie_manager():
    """Compatibility wrapper for remaining CDP handlers during migration."""
    return await _cdp_ensure_cookie_manager(_cdp_cookies_handler_ctx)


# CDP cookie/profile endpoint implementations moved to arena/browser/cdp/cookies.py.



# ---- CDP Network Monitoring ----

async def handle_v1_cdp_network_start(request):
    """POST /v1/browser/cdp/network/start — Start network monitoring."""
    r = require_auth(request)
    if r: return r
    _record_request()
    
    if not _cdp_state["connected"]:
        _record_request(is_error=True, count_request=False)
        return _cors_json_response({"ok": False, "error": "CDP not connected"}, status=400)
    
    cdp = _get_cdp_module()
    if not cdp:
        _record_request(is_error=True, count_request=False)
        return _cors_json_response({"ok": False, "error": "cdp_browser module not found"}, status=500)
    
    try:
        # Get browser from active tab
        tab, _ = await _cdp_active_tab()
        if not tab or not tab._browser:
            _record_request(is_error=True, count_request=False)
            return _cors_json_response({"ok": False, "error": "No active tab with CDP connection"}, status=400)
        
        if _cdp_state.get("monitor") and _cdp_state["monitor"].active:
            return _cors_json_response({"ok": True, "message": "Network monitoring already active"})
        
        max_entries = 1000
        try:
            body = await request.json()
            max_entries = body.get("max_entries", 1000)
        except Exception:
            pass
        
        monitor = cdp.CDPNetworkMonitor(tab._browser, max_entries=max_entries)
        await monitor.start()
        _cdp_state["monitor"] = monitor
        
        return _cors_json_response({
            "ok": True,
            "message": "Network monitoring started",
            "max_entries": max_entries,
        })
    except Exception as e:
        _record_request(is_error=True, count_request=False)
        return _cors_json_response({"ok": False, "error": str(e)}, status=500)


async def handle_v1_cdp_network_stop(request):
    """POST /v1/browser/cdp/network/stop — Stop network monitoring."""
    r = require_auth(request)
    if r: return r
    _record_request()
    
    monitor = _cdp_state.get("monitor")
    if not monitor or not monitor.active:
        return _cors_json_response({"ok": True, "message": "Network monitoring not active"})
    
    try:
        await monitor.stop()
        return _cors_json_response({"ok": True, "message": "Network monitoring stopped"})
    except Exception as e:
        _record_request(is_error=True, count_request=False)
        return _cors_json_response({"ok": False, "error": str(e)}, status=500)


async def handle_v1_cdp_network_requests(request):
    """GET /v1/browser/cdp/network/requests — Get captured network requests.
    
    Query params:
        url_filter: string (optional)
        resource_type: string (optional)
        include_active: bool (default: true)
    """
    r = require_auth(request)
    if r: return r
    _record_request()
    
    monitor = _cdp_state.get("monitor")
    if not monitor:
        return _cors_json_response({"ok": True, "requests": [], "count": 0, "active_count": 0})
    
    qs = parse_qs(request.query_string)
    url_filter = qs.get("url_filter", [None])[0]
    resource_type = qs.get("resource_type", [None])[0]
    include_active = qs.get("include_active", ["true"])[0].lower() == "true"
    
    try:
        finished = monitor.get_requests(url_filter=url_filter, resource_type=resource_type)
        requests_list = [req.to_dict() for req in finished]
        
        result = {
            "ok": True,
            "requests": requests_list,
            "total_finished": monitor.total_requests,
            "active_count": monitor.active_count,
        }
        
        if include_active:
            active = monitor.get_active_requests()
            result["active"] = [req.to_dict() for req in active]
        
        return _cors_json_response(result)
    except Exception as e:
        _record_request(is_error=True, count_request=False)
        return _cors_json_response({"ok": False, "error": str(e)}, status=500)


async def handle_v1_cdp_network_har(request):
    """GET /v1/browser/cdp/network/har — Export captured requests as HAR."""
    r = require_auth(request)
    if r: return r
    _record_request()
    
    monitor = _cdp_state.get("monitor")
    if not monitor:
        return _cors_json_response({"log": {"version": "1.2", "creator": {"name": "arena-cdp", "version": "1.0"}, "entries": []}})
    
    try:
        har = monitor.export_har()
        return _cors_json_response(har)
    except Exception as e:
        _record_request(is_error=True, count_request=False)
        return _cors_json_response({"ok": False, "error": str(e)}, status=500)


# ---- CDP Network Interception ----

async def handle_v1_cdp_intercept_start(request):
    """POST /v1/browser/cdp/intercept/start — Start network interception.
    
    Body JSON (optional):
        patterns: list of Fetch pattern dicts (default: intercept all)
    """
    r = require_auth(request)
    if r: return r
    _record_request()
    
    if not _cdp_state["connected"]:
        _record_request(is_error=True, count_request=False)
        return _cors_json_response({"ok": False, "error": "CDP not connected"}, status=400)
    
    cdp = _get_cdp_module()
    if not cdp:
        _record_request(is_error=True, count_request=False)
        return _cors_json_response({"ok": False, "error": "cdp_browser module not found"}, status=500)
    
    try:
        tab, _ = await _cdp_active_tab()
        if not tab or not tab._browser:
            _record_request(is_error=True, count_request=False)
            return _cors_json_response({"ok": False, "error": "No active tab"}, status=400)
        
        if _cdp_state.get("interceptor") and _cdp_state["interceptor"].active:
            return _cors_json_response({"ok": True, "message": "Interception already active"})
        
        patterns = None
        try:
            body = await request.json()
            patterns = body.get("patterns")
        except Exception:
            pass
        
        interceptor = cdp.CDPNetworkInterceptor(tab._browser)
        await interceptor.start(patterns=patterns)
        _cdp_state["interceptor"] = interceptor
        
        return _cors_json_response({
            "ok": True,
            "message": "Network interception started",
        })
    except Exception as e:
        _record_request(is_error=True, count_request=False)
        return _cors_json_response({"ok": False, "error": str(e)}, status=500)


async def handle_v1_cdp_intercept_stop(request):
    """POST /v1/browser/cdp/intercept/stop — Stop network interception."""
    r = require_auth(request)
    if r: return r
    _record_request()
    
    interceptor = _cdp_state.get("interceptor")
    if not interceptor or not interceptor.active:
        return _cors_json_response({"ok": True, "message": "Interception not active"})
    
    try:
        await interceptor.stop()
        return _cors_json_response({"ok": True, "message": "Interception stopped"})
    except Exception as e:
        _record_request(is_error=True, count_request=False)
        return _cors_json_response({"ok": False, "error": str(e)}, status=500)


async def handle_v1_cdp_intercept_rule(request):
    """POST /v1/browser/cdp/intercept/rule — Add interception rule.
    DELETE /v1/browser/cdp/intercept/rule — Remove interception rule.
    GET /v1/browser/cdp/intercept/rules — List interception rules.
    
    POST Body JSON:
        name: string (required)
        url_pattern: string (optional)
        resource_type: string (optional)
        action: "block" | "redirect" | "modify_headers" | "mock" (required)
        redirect_url: string (for action="redirect")
        mock_status: int (for action="mock", default: 200)
        mock_body: string (for action="mock")
        mock_content_type: string (for action="mock", default: "text/plain")
    
    DELETE Body JSON:
        name: string (required)
    """
    r = require_auth(request)
    if r: return r
    _record_request()
    
    cdp = _get_cdp_module()
    if not cdp:
        _record_request(is_error=True, count_request=False)
        return _cors_json_response({"ok": False, "error": "cdp_browser module not found"}, status=500)
    
    interceptor = _cdp_state.get("interceptor")
    
    if request.method == "GET":
        if not interceptor:
            return _cors_json_response({"ok": True, "rules": [], "count": 0})
        rules = interceptor.get_rules()
        return _cors_json_response({
            "ok": True,
            "rules": [rule.to_dict() for rule in rules],
            "count": len(rules),
        })
    
    try:
        body = await request.json()
    except Exception:
        _record_request(is_error=True, count_request=False)
        return _cors_json_response({"ok": False, "error": "Invalid JSON body"}, status=400)
    
    if request.method == "DELETE":
        name = body.get("name")
        if not name:
            _record_request(is_error=True, count_request=False)
            return _cors_json_response({"ok": False, "error": "missing 'name'"}, status=400)
        
        if not interceptor:
            _record_request(is_error=True, count_request=False)
            return _cors_json_response({"ok": False, "error": "No active interceptor"}, status=400)
        
        removed = interceptor.remove_rule(name)
        return _cors_json_response({
            "ok": removed,
            "name": name,
        })
    
    # POST — add rule
    if not interceptor or not interceptor.active:
        _record_request(is_error=True, count_request=False)
        return _cors_json_response({"ok": False, "error": "Interception not active. Start first."}, status=400)
    
    name = body.get("name", "")
    action = body.get("action")
    if not action:
        _record_request(is_error=True, count_request=False)
        return _cors_json_response({"ok": False, "error": "missing 'action'"}, status=400)
    
    try:
        rule = cdp.InterceptRule(
            name=name,
            url_pattern=body.get("url_pattern"),
            resource_type=body.get("resource_type"),
            action=action,
            redirect_url=body.get("redirect_url"),
            mock_status=body.get("mock_status", 200),
            mock_body=body.get("mock_body"),
            mock_content_type=body.get("mock_content_type", "text/plain"),
            modify_request_headers=body.get("modify_request_headers"),
            remove_request_headers=body.get("remove_request_headers"),
        )
        interceptor.add_rule(rule)
        
        return _cors_json_response({
            "ok": True,
            "rule": rule.to_dict(),
        })
    except ValueError as e:
        return _cors_json_response({"ok": False, "error": str(e)}, status=400)
    except Exception as e:
        _record_request(is_error=True, count_request=False)
        return _cors_json_response({"ok": False, "error": str(e)}, status=500)


# ---- CDP Session Health Check ----

async def handle_v1_cdp_session_check(request):
    """GET /v1/browser/cdp/session/check — Check session health.
    
    Query params:
        domain: string (required)
        auth_cookie_names: string (comma-separated, optional)
    """
    r = require_auth(request)
    if r: return r
    _record_request()
    
    if not _cdp_state["connected"]:
        return _cors_json_response({
            "ok": False,
            "connected": False,
            "error": "CDP not connected",
            "detail": "Start or connect a CDP browser session with POST /v1/browser/cdp/connect before checking cookies/session state.",
            "status_endpoint": "/v1/browser/cdp/status",
            "connect_endpoint": "/v1/browser/cdp/connect",
        })
    
    qs = parse_qs(request.query_string)
    domain = qs.get("domain", [None])[0]
    if not domain:
        _record_request(is_error=True, count_request=False)
        return _cors_json_response({"ok": False, "error": "missing 'domain' parameter"}, status=400)
    
    auth_names_str = qs.get("auth_cookie_names", [None])[0]
    auth_cookie_names = auth_names_str.split(",") if auth_names_str else None
    
    try:
        cookie_mgr = await _ensure_cookie_manager()
        if not cookie_mgr:
            _record_request(is_error=True, count_request=False)
            return _cors_json_response({"ok": False, "error": "Failed to start cookie manager"}, status=500)
        
        result = await cookie_mgr.check_session(domain, auth_cookie_names)
        return _cors_json_response({"ok": True, **result})
    except Exception as e:
        _record_request(is_error=True, count_request=False)
        return _cors_json_response({"ok": False, "error": str(e)}, status=500)


# ---- CDP Stealth Extract/Shot (BrowserAct + CDP integration) ----

async def _cdp_get_active_browser():
    """Get the active tab's CDPBrowser instance, or None."""
    mgr = _cdp_state.get("manager")
    if not mgr or not _cdp_state["connected"]:
        return None
    tab = mgr.active_tab
    if not tab or not tab.connected:
        return None
    return tab._browser


async def handle_v1_cdp_stealth_extract(request):
    """POST /v1/browser/cdp/stealth/extract — Navigate to URL via CDP and extract page content.

    Uses the existing CDP connection for stealth-aware content extraction,
    similar to browser-act extract but without launching a separate browser.

    Body JSON:
        url: string (required)
        wait_for: string (optional CSS selector to wait for)
        timeout: float (default: 15s)
    """
    r = require_auth(request)
    if r: return r
    _record_request()

    if not _cdp_state["connected"]:
        _record_request(is_error=True, count_request=False)
        return _cors_json_response({"ok": False, "error": "CDP not connected"}, status=400)

    try:
        body = await request.json()
    except Exception:
        _record_request(is_error=True, count_request=False)
        return _cors_json_response({"ok": False, "error": "Invalid JSON body"}, status=400)

    url = body.get("url")
    if not url:
        _record_request(is_error=True, count_request=False)
        return _cors_json_response({"ok": False, "error": "missing 'url'"}, status=400)

    wait_for = body.get("wait_for")
    timeout = body.get("timeout", 15)

    browser = await _cdp_get_active_browser()
    if not browser:
        _record_request(is_error=True, count_request=False)
        return _cors_json_response({"ok": False, "error": "No active tab connected"}, status=400)

    try:
        # Navigate to the URL
        await asyncio.wait_for(browser.navigate(url, wait=True), timeout=timeout)

        # Wait for specific element if requested
        if wait_for:
            safe_selector = json.dumps(wait_for)
            expr = f"new Promise((resolve, reject) => {{ const check = () => {{ if (document.querySelector({safe_selector})) resolve(true); else setTimeout(check, 200); }}; setTimeout(() => reject('timeout'), {(timeout-2)*1000}); check(); }})"
            await asyncio.wait_for(
                browser.eval_js(expr),
                timeout=timeout
            )

        # Extract content
        html = await asyncio.wait_for(browser.dump_dom(), timeout=10)
        title = await asyncio.wait_for(browser.eval_js("document.title"), timeout=5)
        current_url = await asyncio.wait_for(browser.eval_js("window.location.href"), timeout=5)

        # Extract text content using Readability-like approach
        text_content = await asyncio.wait_for(
            browser.eval_js(
                "document.body ? document.body.innerText.substring(0, 50000) : ''"
            ),
            timeout=10
        )

        # Extract metadata
        meta = await asyncio.wait_for(
            browser.eval_js("""
                (function() {
                    var meta = {};
                    var desc = document.querySelector('meta[name="description"]');
                    if (desc) meta.description = desc.content;
                    var ogTitle = document.querySelector('meta[property="og:title"]');
                    if (ogTitle) meta.og_title = ogTitle.content;
                    var ogDesc = document.querySelector('meta[property="og:description"]');
                    if (ogDesc) meta.og_description = ogDesc.content;
                    return JSON.stringify(meta);
                })()
            """),
            timeout=5
        )

        result = {
            "ok": True,
            "url": current_url,
            "title": title,
            "html_len": len(html) if html else 0,
            "text_len": len(text_content) if text_content else 0,
            "text": (text_content or "")[:20000],
            "metadata": json.loads(meta) if meta else {},
        }

        return _cors_json_response(result)

    except asyncio.TimeoutError:
        _record_request(is_error=True, count_request=False)
        return _cors_json_response({"ok": False, "error": f"Extraction timed out ({timeout}s)"}, status=408)
    except Exception as e:
        _record_request(is_error=True, count_request=False)
        return _cors_json_response({"ok": False, "error": str(e)}, status=500)


async def handle_v1_cdp_stealth_shot(request):
    """POST /v1/browser/cdp/stealth/shot — Navigate to URL via CDP and take a screenshot.

    Uses the existing CDP connection for stealth-aware screenshots,
    similar to browser-act shot but without launching a separate browser.

    Body JSON:
        url: string (required)
        width: int (default: 1280)
        height: int (default: 720)
        full_page: bool (default: false)
        format: string ("png" or "jpeg", default: "png")
        timeout: float (default: 15s)
    """
    r = require_auth(request)
    if r: return r
    _record_request()

    if not _cdp_state["connected"]:
        _record_request(is_error=True, count_request=False)
        return _cors_json_response({"ok": False, "error": "CDP not connected"}, status=400)

    try:
        body = await request.json()
    except Exception:
        _record_request(is_error=True, count_request=False)
        return _cors_json_response({"ok": False, "error": "Invalid JSON body"}, status=400)

    url = body.get("url")
    if not url:
        _record_request(is_error=True, count_request=False)
        return _cors_json_response({"ok": False, "error": "missing 'url'"}, status=400)

    full_page = body.get("full_page", False)
    img_format = body.get("format", "png")
    timeout = body.get("timeout", 15)
    width = body.get("width", 1280)
    height = body.get("height", 720)

    browser = await _cdp_get_active_browser()
    if not browser:
        _record_request(is_error=True, count_request=False)
        return _cors_json_response({"ok": False, "error": "No active tab connected"}, status=400)

    try:
        # Set viewport size
        await asyncio.wait_for(
            browser.send("Emulation.setDeviceMetricsOverride", {
                "width": width, "height": height,
                "deviceScaleFactor": 1, "mobile": False,
            }),
            timeout=5
        )

        # Navigate
        await asyncio.wait_for(browser.navigate(url, wait=True), timeout=timeout)

        # Take screenshot
        params = {"format": img_format}
        if full_page:
            params["captureBeyondViewport"] = True
        res = await asyncio.wait_for(browser.send("Page.captureScreenshot", params), timeout=15)

        if res and "result" in res and "data" in res["result"]:
            return _cors_json_response({
                "ok": True,
                "url": url,
                "format": img_format,
                "data": res["result"]["data"],
                "width": width,
                "height": height,
                "full_page": full_page,
            })
        else:
            _record_request(is_error=True, count_request=False)
            return _cors_json_response({"ok": False, "error": "Screenshot returned no data"}, status=500)

    except asyncio.TimeoutError:
        _record_request(is_error=True, count_request=False)
        return _cors_json_response({"ok": False, "error": f"Screenshot timed out ({timeout}s)"}, status=408)
    except Exception as e:
        _record_request(is_error=True, count_request=False)
        return _cors_json_response({"ok": False, "error": str(e)}, status=500)


async def handle_v1_cdp_health(request):
    """GET /v1/browser/cdp/health — CDP connection health dashboard.

    Returns comprehensive health info including:
    - Connection status and uptime
    - Browser process status
    - WebSocket health
    - Reconnect history
    - Active tab info
    - Memory/resource usage
    """
    r = require_auth(request)
    if r: return r
    _record_request()

    mgr = _cdp_state.get("manager")
    connected = _cdp_state["connected"]

    health = {
        "ok": True,
        "connected": connected,
        "port": _cdp_state["port"],
        "headless": _cdp_state["headless"],
        "watcher_active": _cdp_watcher_task is not None and not _cdp_watcher_task.done(),
        "reconnect_count": _cdp_state.get("reconnect_count", 0),
        "last_connect_time": _cdp_state.get("last_connect_time"),
        "last_disconnect_reason": _cdp_state.get("last_disconnect_reason"),
        "bridge_uptime_s": round(time.time() - BRIDGE_METRICS["start_time"]),
    }

    if connected and mgr:
        # Browser process info
        if mgr._browser_proc:
            proc = mgr._browser_proc
            health["browser"] = {
                "pid": proc.pid,
                "alive": proc.poll() is None,
                "returncode": proc.returncode,
            }
        else:
            health["browser"] = {"alive": False, "note": "External browser (not launched by bridge)"}

        # Tab info
        tabs = mgr.list_tabs()
        health["tabs"] = {
            "count": len(tabs),
            "active_id": mgr.active_tab_id,
            "details": [t.to_dict() for t in tabs[:10]],
        }

        # Active tab health probe
        if mgr.active_tab and mgr.active_tab.connected:
            health["active_tab"] = {
                "connected": True,
                "target_id": mgr.active_tab.target_id,
                "url": mgr.active_tab.url,
                "title": mgr.active_tab.title,
            }
            # Quick health check — can we evaluate JS?
            try:
                result = await asyncio.wait_for(mgr.active_tab.eval_js("1+1"), timeout=3)
                health["active_tab"]["health_probe"] = "ok" if result == 2 else f"unexpected result: {result}"
            except asyncio.TimeoutError:
                health["active_tab"]["health_probe"] = "timeout"
            except ConnectionError:
                health["active_tab"]["health_probe"] = "disconnected"
            except Exception as e:
                health["active_tab"]["health_probe"] = f"error: {type(e).__name__}"
        else:
            health["active_tab"] = {"connected": False}

        # Connection uptime
        if _cdp_state.get("last_connect_time"):
            try:
                last = datetime.fromisoformat(_cdp_state["last_connect_time"])
                uptime = (datetime.now(timezone.utc) - last).total_seconds()
                health["connection_uptime_s"] = round(uptime)
            except Exception:
                pass

    else:
        health["browser"] = {"alive": False}
        health["tabs"] = {"count": 0}
        health["active_tab"] = {"connected": False}

    # System resource usage
    try:
        import resource as _resource
        usage = _resource.getrusage(_resource.RUSAGE_SELF)
        health["resources"] = {
            "max_rss_mb": round(usage.ru_maxrss / 1024, 1),
            "user_cpu_s": round(usage.ru_utime, 1),
            "sys_cpu_s": round(usage.ru_stime, 1),
        }
    except Exception:
        pass

    return _cors_json_response(health)


def _recall_sync(query: str, top: int) -> dict:
    return memory_recall(query, facts=_load_facts(), top=top)




# --- /v1/recall/digest GET — Memory digest ---

def _recall_digest_sync() -> dict:
    return memory_recall_digest(facts=_load_facts(), audit_lines=read_tail(AUDIT, 20), utc_now_fn=utc_now)


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
handle_v1_memory = _memory_handlers.memory_get
handle_v1_memory_set = _memory_handlers.memory_set
handle_v1_memory_delete = _memory_handlers.memory_delete
handle_v1_recall = _memory_handlers.recall
handle_v1_recall_digest = _memory_handlers.recall_digest




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
handle_v1_audit = _observability_handlers.audit
handle_v1_audit_stats = _observability_handlers.audit_stats
handle_v1_audit_log = _observability_handlers.audit_log
handle_v1_webhooks_get = _observability_handlers.webhooks_get
handle_v1_webhooks_set = _observability_handlers.webhooks_set




# --- /v1/tasks GET — Task queue management ---

def _tasks_list_sync(status: str, limit: int) -> dict:
    """List JSON files in queue directories."""
    return list_tasks(inbox=INBOX, running=RUNNING, done=DONE, failed=FAILED, status=status, limit=limit)




# --- /v1/tasks POST — Submit task ---

def _task_submit_sync(data: dict) -> dict:
    """Create JSON file in INBOX. Supports both cmd-based and title-based tasks."""
    return submit_task(data, inbox=INBOX, default_cwd=str(Path.home()), now_fn=utc_now)




# --- /v1/tasks/clean POST — Clean completed tasks ---

def _tasks_clean_sync() -> dict:
    """Remove done/failed task files older than 24h."""
    return clean_tasks(done=DONE, failed=FAILED, older_than_seconds=86400)


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
handle_v1_tasks_get = _task_handlers.tasks_get
handle_v1_tasks_post = _task_handlers.tasks_post
handle_v1_tasks_clean = _task_handlers.tasks_clean




# --- /v1/skills GET — List skills ---

def _skills_list_sync() -> dict:
    """Scan arena-bridge/skills/ directory for skill definitions."""
    return scan_skills(SKILLS_DIR)

def _parse_skill_folder(d: Path, skills: list, is_third_party: bool = False, category: str = ""):
    """Compatibility wrapper for old internal parser API."""
    skills.append(parse_skill_folder(SKILLS_DIR, d, is_third_party=is_third_party, category=category))




def _skill_install_sync(name: str, url: str) -> dict:
    return install_skill(name, url, skills_dir=SKILLS_DIR)

def _normalize_third_party_skill_name(name: str) -> tuple[str | None, str | None]:
    return normalize_third_party_skill_name(name)


def _skill_uninstall_sync(name: str) -> dict:
    return uninstall_skill(name, skills_dir=SKILLS_DIR)





# --- /v1/skills/run POST — Run a skill ---

def _skills_run_sync(name: str, args: list[str], env_extra: dict | None = None) -> dict:
    return run_skill(
        name,
        args,
        skills_dir=SKILLS_DIR,
        root_agent=ROOT_AGENT,
        bin_dir=BIN,
        subprocess_kwargs_fn=_subprocess_kwargs,
        env_extra=env_extra,
    )


def _skill_path_is_safe(name: str) -> bool:
    try:
        resolved = (SKILLS_DIR / name).resolve()
        return str(resolved).startswith(str(SKILLS_DIR.resolve()))
    except Exception:
        return False


_skill_handler_ctx = SkillHandlerContext(
    require_auth=require_auth,
    record_request=_record_request,
    cors_json_response=_cors_json_response,
    executor=_EXECUTOR,
    skills_list_with_cache=_skills_list_sync_with_cache,
    skills_cache_reset=_skills_cache_reset,
    skill_install_sync=_skill_install_sync,
    skill_uninstall_sync=_skill_uninstall_sync,
    skills_run_sync=_skills_run_sync,
    skill_path_is_safe=_skill_path_is_safe,
    audit=audit,
    log_info=log.info,
)
_skill_handlers = make_skill_handlers(_skill_handler_ctx)
handle_v1_skills = _skill_handlers.skills
handle_v1_skills_install = _skill_handlers.install
handle_v1_skills_uninstall = _skill_handlers.uninstall
handle_v1_skills_run = _skill_handlers.run
handle_v1_skills_reload = _skill_handlers.reload




# --- /v1/hooks GET — List hooks ---

def _hooks_list_sync() -> dict:
    return list_hooks(HOOKS_DIR)




# --- /v1/agents GET — List agent configs ---

def _agents_list_sync() -> dict:
    return list_agents(AGENTS_DIR)




# --- /v1/subagents GET — List subagents ---

def _subagents_list_sync() -> dict:
    return list_subagents(SUBAGENTS_DIR)




# --- /v1/subagents/spawn POST — Spawn subagent ---

def _subagents_spawn_sync(data: dict) -> dict:
    return spawn_subagent(data, bin_dir=BIN, subprocess_kwargs_fn=_subprocess_kwargs)




# --- /v1/mission/show GET — Show mission details ---

def _mission_show_sync(name: str) -> dict:
    return show_mission(MISSIONS_DIR, name)


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
handle_v1_missions = _resource_handlers.missions
handle_v1_reports = _resource_handlers.reports
handle_v1_hooks = _resource_handlers.hooks
handle_v1_agents = _resource_handlers.agents
handle_v1_subagents = _resource_handlers.subagents
handle_v1_subagents_spawn = _resource_handlers.subagents_spawn
handle_v1_mission_show = _resource_handlers.mission_show




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


def _signal_handler(sig: int, frame: Any) -> None:
    """Signal handler for graceful shutdown."""
    sig_name = signal.Signals(sig).name if hasattr(signal, "Signals") else str(sig)
    log.info("[UnifiedBridge] Received %s, shutting down gracefully...", sig_name)
    
    # Stop watchdog (Phase 3)
    try:
        _stop_watchdog()
    except Exception:
        pass

    # Stop CDP watcher
    try:
        _stop_cdp_watcher()
    except Exception:
        pass
    
    # Close CDP connection synchronously (we're in a signal handler, can't await)
    try:
        if _cdp_state.get("manager"):
            mgr = _cdp_state["manager"]
            # Try to kill browser process if we launched it
            if mgr._browser_proc and mgr._browser_proc.poll() is None:
                mgr._browser_proc.terminate()
                try:
                    mgr._browser_proc.wait(timeout=3)
                except Exception:
                    mgr._browser_proc.kill()
    except Exception:
        pass
    
    if _shutdown_event is not None:
        _shutdown_event.set()
    # Force exit after a short delay if event loop doesn't stop
    threading.Timer(5.0, lambda: os._exit(0)).start()


# ============================================================================
# MAIN
# ============================================================================

def resolve_token(cli_token: str | None) -> tuple[str, Path]:
    """Resolve auth token: CLI arg > env var > token.txt > auto-generate.
    Returns (token, file_path_that_is_the_canonical_source_for_THIS_instance).
    file_path is the location where regen should write back."""
    # Resolve the actual file location first (env > default)
    env_file = os.environ.get("ARENA_TOKEN_FILE")
    token_file = Path(env_file).expanduser() if env_file else TOKEN_FILE

    # 1. CLI --token argument
    if cli_token:
        return cli_token, token_file
    # 2. Environment variable for token value
    env_tok = os.environ.get("ARENA_LOCAL_BRIDGE_TOKEN")
    if env_tok:
        return env_tok, token_file
    # 3. Read from token.txt
    try:
        existing = token_file.read_text(encoding="utf-8").strip()
        if existing and len(existing) >= 16:
            return existing, token_file
    except FileNotFoundError:
        pass
    except Exception:
        pass
    # 4. Auto-generate a new token and save it (to the resolved path)
    new_tok = b64_token()
    token_file.parent.mkdir(parents=True, exist_ok=True)
    token_file.write_text(new_tok + "\n", encoding="utf-8")
    try:
        os.chmod(token_file, 0o600)
    except Exception:
        pass
    log.info("[ArenaBridge] New token generated and saved to %s", token_file)
    return new_tok, token_file


def _daemonize() -> None:
    """Double-fork to daemonize on Linux."""
    if os.name != "nt":
        # First fork
        try:
            pid = os.fork()
            if pid > 0:
                os._exit(0)
        except OSError as e:
            log.error("[ArenaBridge] First fork failed: %s", e)
            return

        # Decouple from parent
        os.setsid()
        os.umask(0)

        # Second fork
        try:
            pid = os.fork()
            if pid > 0:
                os._exit(0)
        except OSError as e:
            log.error("[ArenaBridge] Second fork failed: %s", e)
            return

        # Redirect standard file descriptors
        # stdout/stderr go to /dev/null — the Python logging module's
        # RotatingFileHandler already writes to bridge.log with proper
        # rotation. Previously, dup2 to bridge.log caused unbounded growth
        # because aiohttp access logs bypassed the RotatingFileHandler.
        sys.stdout.flush()
        sys.stderr.flush()
        devnull_r = open(os.devnull, "r")
        os.dup2(devnull_r.fileno(), sys.stdin.fileno())
        devnull_r.close()
        devnull_w = open(os.devnull, "w")
        os.dup2(devnull_w.fileno(), sys.stdout.fileno())
        os.dup2(devnull_w.fileno(), sys.stderr.fileno())
        devnull_w.close()




# /v1/logs handler now lives in arena/observability/runtime_handlers.py.




def serve(args: argparse.Namespace) -> None:
    # Handle --background daemonization (Linux only)
    if getattr(args, "background", False) and os.name != "nt":
        _daemonize()

    # Ensure session environment variables are set (critical for systemd)
    _ensure_session_env()

    # Load optional config file
    file_cfg = _load_config_file()
    if file_cfg.get("port"):
        args.port = int(file_cfg["port"])
    if file_cfg.get("profile"):
        args.profile = file_cfg["profile"]
    if file_cfg.get("timeout"):
        args.timeout = int(file_cfg["timeout"])
    if file_cfg.get("max_concurrent"):
        args.max_concurrent = int(file_cfg["max_concurrent"])
    if file_cfg.get("bind"):
        args.bind = file_cfg["bind"]
    cdp_cfg = file_cfg.get("cdp", {})
    if cdp_cfg.get("port"):
        _cdp_state["port"] = int(cdp_cfg["port"])
    if cdp_cfg.get("headless") is not None:
        _cdp_state["headless"] = bool(cdp_cfg["headless"])
    if file_cfg.get("rate_limit"):
        global _rate_limit_max, _rate_limit_window
        rl = file_cfg["rate_limit"]
        if rl.get("max_requests"):
            _rate_limit_max = int(rl["max_requests"])
        if rl.get("window_seconds"):
            _rate_limit_window = float(rl["window_seconds"])

    # If --token-file was provided, set env var so resolve_token() finds it
    tf = getattr(args, "token_file", "") or ""
    if tf:
        os.environ["ARENA_TOKEN_FILE"] = tf

    token, token_file_used = resolve_token(args.token)

    root = Path(args.root).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)

    cfg = {
        "token": token,
        "token_file": str(token_file_used),  # exact file THIS instance reads
        "profile": args.profile,
        "root": root,
        "port": args.port,
        "allow_any_cwd": args.allow_any_cwd,
        "timeout": args.timeout,
        "max_timeout": args.max_timeout,
        "max_output": args.max_output,
        "max_concurrent": args.max_concurrent,
        "semaphore": None,  # Created in on_startup after event loop is running
        "active_exec": 0,
    }

    app = make_app(cfg)

    # v2.1.0: Rotate oversized logs before starting the server
    _rotate_all_logs_on_startup()

    # Set up graceful shutdown signal handlers
    global _shutdown_event
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            signal.signal(sig, _signal_handler)
        except (OSError, ValueError):
            pass  # Can't set signal handler in non-main thread

    log.info("Arena Unified Bridge v%s on http://%s:%s", VERSION, args.bind, args.port)
    log.info("profile=%s root=%s audit=%s max_concurrent=%s", args.profile, root, AUDIT, args.max_concurrent)
    log.info("All services multiplexed on single port: bridge, MCP, SSE, WS, gateway, dashboard, task-runner")
    log.info("Stop with Ctrl+C.")

    # access_log=None disables aiohttp's default AccessLogger which writes
    # every HTTP request to stderr — this was the #1 cause of disk fill bugs.
    web.run_app(app, host=args.bind, port=args.port, print=None, access_log=None)


def token_cmd(_: argparse.Namespace) -> None:
    log.info("New token: %s", b64_token())


def main() -> None:
    p = argparse.ArgumentParser(description="Arena Unified Bridge")
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("token", help="Generate a strong random token")
    sp.set_defaults(func=token_cmd)

    sp = sub.add_parser("serve", help="Run unified bridge")
    sp.add_argument("--bind", default="127.0.0.1",
                     help="Bind address (default: 127.0.0.1, use 0.0.0.0 for remote access)")
    sp.add_argument("--port", type=int, default=8765)
    sp.add_argument("--token")
    sp.add_argument("--token-file", dest="token_file", default="",
                     help="Path to token file (default: ~/arena-bridge/token.txt)")
    sp.add_argument("--root", default=str(Path.home()))
    sp.add_argument("--allow-any-cwd", action="store_true")
    sp.add_argument("--profile", choices=["cautious", "owner-shell"], default="cautious")
    sp.add_argument("--timeout", type=int, default=60)
    sp.add_argument("--max-timeout", type=int, default=600)
    sp.add_argument("--max-output", type=int, default=DEFAULT_MAX_OUTPUT)
    sp.add_argument("--max-concurrent", type=int, default=DEFAULT_MAX_CONCURRENT)
    sp.add_argument("--background", action="store_true",
                     help="Daemonize on Linux (fork + detach)")
    sp.set_defaults(func=serve)

    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
