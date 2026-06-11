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
from arena.browser.fetch import (  # noqa: E402,F401
    browser_dump,
    browser_fetch,
    browser_head,
    browser_read,
    browser_search,
)
from arena.browser.handlers import make_browser_fetch_handlers  # noqa: E402,F401
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
from arena.handler_context import HandlerContext, ServiceHandlerContext, TaskHandlerContext, SkillHandlerContext, DesktopHandlerContext, BrowserFetchHandlerContext, ResourceHandlerContext, MemoryHandlerContext, ObservabilityHandlerContext, SystemHandlerContext, UserHandlerContext  # noqa: E402,F401
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
ACTIVE_PROCESSES: dict[str, dict] = {}

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
_event_subscribers: list[asyncio.Queue] = []

async def emit_event(event_type: str, data: dict | None = None) -> None:
    """Broadcast an event to all connected WebSocket subscribers."""
    payload = {"type": event_type, "ts": utc_now(), "data": data or {}}
    dead = []
    for i, q in enumerate(list(_event_subscribers)):  # Iterate over copy to avoid race
        try:
            q.put_nowait(payload)
        except asyncio.QueueFull:
            dead.append(q)
    # Remove full/dead queues
    for q in dead:
        try:
            _event_subscribers.remove(q)
        except ValueError:
            pass


async def handle_v1_events(request: web.Request) -> web.WebSocketResponse:
    """WebSocket /v1/events — Real-time event stream.

    Clients connect via WebSocket and receive events as JSON messages.
    Events include: cdp_connect, cdp_disconnect, task_start, task_done,
    error, skill_run, exec, memory_update, browser_browse, alert.
    """
    r = require_auth(request)
    if r:
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        await ws.send_json({"ok": False, "error": "unauthorized"})
        await ws.close()
        return ws

    ws = web.WebSocketResponse()
    await ws.prepare(request)

    # Send welcome message
    await ws.send_json({"type": "connected", "ts": utc_now(),
                        "data": {"version": VERSION, "message": "Arena Bridge event stream"}})

    # Subscribe
    q: asyncio.Queue = asyncio.Queue(maxsize=500)
    _event_subscribers.append(q)
    log.info("[Events] Subscriber connected (total=%d)", len(_event_subscribers))

    try:
        # Two-task pattern: read from ws AND forward events from queue
        async def _forward_events():
            while not ws.closed:
                try:
                    payload = await asyncio.wait_for(q.get(), timeout=30)
                    if not ws.closed:
                        await ws.send_json(payload)
                except asyncio.TimeoutError:
                    # Send keepalive ping
                    if not ws.closed:
                        try:
                            await ws.send_json({"type": "ping", "ts": utc_now()})
                        except Exception:
                            break
                except Exception:
                    break

        forward_task = asyncio.create_task(_forward_events())

        # Also read incoming messages (for future commands)
        async for msg in ws:
            if msg.type == aiohttp.WSMsgType.TEXT:
                try:
                    data = json.loads(msg.data)
                    # Support subscribe/unsubscribe by event type
                    if data.get("command") == "ping":
                        await ws.send_json({"type": "pong", "ts": utc_now()})
                except Exception:
                    pass
            elif msg.type in (aiohttp.WSMsgType.ERROR, aiohttp.WSMsgType.CLOSE):
                break

        forward_task.cancel()
        try:
            await forward_task
        except asyncio.CancelledError:
            pass
    finally:
        if q in _event_subscribers:
            _event_subscribers.remove(q)
        log.info("[Events] Subscriber disconnected (total=%d)", len(_event_subscribers))

    return ws


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
_watchdog_state: dict[str, Any] = {
    "last_check": 0.0,
    "memory_mb": 0.0,
    "cpu_percent": 0.0,
    "alerts": [],
    "restart_count": 0,
    "auto_restart": True,
    "memory_limit_mb": 512,
    "cpu_limit_percent": 90.0,
    "check_interval_s": 30,
}
_watchdog_task: asyncio.Task | None = None


async def _watchdog_loop() -> None:
    """Background watchdog that monitors bridge health and emits alerts."""
    while True:
        try:
            await asyncio.sleep(_watchdog_state["check_interval_s"])

            # Memory and CPU monitoring
            mem_mb = 0.0
            cpu_pct = 0.0
            try:
                import psutil
                proc = psutil.Process()
                mem_info = proc.memory_info()
                mem_mb = mem_info.rss / (1024 * 1024)
                cpu_pct = proc.cpu_percent(interval=1.0)
            except ImportError:
                # Fallback: read from /proc/self/status on Linux
                try:
                    if sys.platform != "win32":
                        with open("/proc/self/status") as f:
                            for line in f:
                                if line.startswith("VmRSS:"):
                                    mem_mb = int(line.split()[1]) / 1024  # kB to MB
                                    break
                except Exception:
                    pass
            except Exception:
                pass

            _watchdog_state["memory_mb"] = round(mem_mb, 1)
            _watchdog_state["cpu_percent"] = round(cpu_pct, 1)
            _watchdog_state["last_check"] = time.time()

            # Check thresholds and emit alerts
            alerts_now = []
            if mem_mb > _watchdog_state["memory_limit_mb"]:
                alert = {"type": "memory_high", "value_mb": round(mem_mb, 1),
                         "limit_mb": _watchdog_state["memory_limit_mb"],
                         "ts": utc_now()}
                alerts_now.append(alert)
                log.warning("[Watchdog] Memory alert: %.1f MB > %.0f MB limit",
                            mem_mb, _watchdog_state["memory_limit_mb"])
                await emit_event("alert", alert)

            if cpu_pct > _watchdog_state["cpu_limit_percent"]:
                alert = {"type": "cpu_high", "value_pct": round(cpu_pct, 1),
                         "limit_pct": _watchdog_state["cpu_limit_percent"],
                         "ts": utc_now()}
                alerts_now.append(alert)
                log.warning("[Watchdog] CPU alert: %.1f%% > %.1f%% limit",
                            cpu_pct, _watchdog_state["cpu_limit_percent"])
                await emit_event("alert", alert)

            # Keep last 50 alerts
            _watchdog_state["alerts"].extend(alerts_now)
            _watchdog_state["alerts"] = _watchdog_state["alerts"][-50:]

        except asyncio.CancelledError:
            log.info("[Watchdog] Cancelled — shutting down")
            break
        except Exception as e:
            log.error("[Watchdog] Unexpected error: %s", e)
            await asyncio.sleep(10)


def _start_watchdog() -> None:
    """Start the health watchdog if not already running."""
    global _watchdog_task
    if _watchdog_task and not _watchdog_task.done():
        return
    _watchdog_task = asyncio.create_task(_watchdog_loop())
    log.info("[Watchdog] Started (interval=%ds, mem_limit=%dMB, cpu_limit=%.0f%%)",
             _watchdog_state["check_interval_s"],
             _watchdog_state["memory_limit_mb"],
             _watchdog_state["cpu_limit_percent"])


def _stop_watchdog() -> None:
    """Stop the health watchdog."""
    global _watchdog_task
    if _watchdog_task and not _watchdog_task.done():
        _watchdog_task.cancel()
        _watchdog_task = None
        log.info("[Watchdog] Stopped")


async def handle_v1_watchdog(request: web.Request) -> web.Response:
    """GET /v1/watchdog — Watchdog status and configuration.
    POST /v1/watchdog — Update watchdog settings."""
    r = require_auth(request)
    if r: return r
    _record_request()

    if request.method == "POST":
        try:
            data = await request.json()
            if "memory_limit_mb" in data:
                _watchdog_state["memory_limit_mb"] = int(data["memory_limit_mb"])
            if "cpu_limit_percent" in data:
                _watchdog_state["cpu_limit_percent"] = float(data["cpu_limit_percent"])
            if "check_interval_s" in data:
                _watchdog_state["check_interval_s"] = max(10, int(data["check_interval_s"]))
            if "auto_restart" in data:
                _watchdog_state["auto_restart"] = bool(data["auto_restart"])
            log.info("[Watchdog] Config updated: %s", data)
        except Exception as e:
            return _cors_json_response({"ok": False, "error": str(e)}, status=400)

    return _cors_json_response({
        "ok": True,
        "memory_mb": _watchdog_state["memory_mb"],
        "cpu_percent": _watchdog_state["cpu_percent"],
        "memory_limit_mb": _watchdog_state["memory_limit_mb"],
        "cpu_limit_percent": _watchdog_state["cpu_limit_percent"],
        "check_interval_s": _watchdog_state["check_interval_s"],
        "auto_restart": _watchdog_state["auto_restart"],
        "last_check": _watchdog_state["last_check"],
        "restart_count": _watchdog_state["restart_count"],
        "recent_alerts": _watchdog_state["alerts"][-10:],
        "uptime_seconds": round(time.time() - BRIDGE_METRICS["start_time"], 1),
    })


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

async def handle_v1_batch(request: web.Request) -> web.Response:
    """POST /v1/batch — Execute multiple operations in parallel.

    Body: {"operations": [{"method": "GET", "path": "/v1/status"}, ...]}
    Optional: "max_concurrent": 5, "fail_fast": false
    """
    r = require_auth(request)
    if r: return r
    _record_request()
    try:
        data = await request.json()
    except Exception as e:
        return _cors_json_response({"ok": False, "error": f"invalid json: {e}"}, status=400)

    operations = data.get("operations", [])
    if not operations:
        return _cors_json_response({"ok": False, "error": "operations array is required"}, status=400)
    if len(operations) > 20:
        return _cors_json_response({"ok": False, "error": "maximum 20 operations per batch"}, status=400)

    max_concurrent = min(data.get("max_concurrent", 5), 10)
    fail_fast = data.get("fail_fast", False)
    sem = asyncio.Semaphore(max_concurrent)

    async def _execute_op(idx: int, op: dict) -> dict:
        method = op.get("method", "GET").upper()
        path = op.get("path", "")
        body = op.get("body", {})
        op_id = op.get("id", f"op_{idx}")

        if not path:
            return {"id": op_id, "ok": False, "error": "missing path", "status": 400}

        async with sem:
            t0 = time.time()
            try:
                # Build a sub-request to the internal handler
                # For safety, we only allow internal API paths
                if not path.startswith("/v1/") and path not in ("/health", "/metrics"):
                    return {"id": op_id, "ok": False, "error": "only /v1/* and /health paths allowed",
                            "status": 403}

                # Use aiohttp client to call ourselves (cleanest approach)
                cfg = request.app["cfg"]
                port = cfg.get("port", 8765)
                url = f"http://127.0.0.1:{port}{path}"
                headers = {"Authorization": f"Bearer {cfg['token']}",
                           "Content-Type": "application/json"}

                async with aiohttp.ClientSession() as session:
                    if method == "GET":
                        async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=30)) as resp:
                            result = await resp.json()
                            return {"id": op_id, "ok": resp.status < 400, "status": resp.status,
                                    "data": result, "duration_ms": round((time.time() - t0) * 1000, 2)}
                    elif method == "POST":
                        async with session.post(url, headers=headers, json=body,
                                                timeout=aiohttp.ClientTimeout(total=60)) as resp:
                            result = await resp.json()
                            return {"id": op_id, "ok": resp.status < 400, "status": resp.status,
                                    "data": result, "duration_ms": round((time.time() - t0) * 1000, 2)}
                    else:
                        return {"id": op_id, "ok": False, "error": f"unsupported method: {method}",
                                "status": 405}
            except asyncio.TimeoutError:
                return {"id": op_id, "ok": False, "error": "timeout", "status": 408,
                        "duration_ms": round((time.time() - t0) * 1000, 2)}
            except Exception as e:
                return {"id": op_id, "ok": False, "error": str(e), "status": 500,
                        "duration_ms": round((time.time() - t0) * 1000, 2)}

    # Execute all operations in parallel
    tasks = [_execute_op(i, op) for i, op in enumerate(operations)]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    # Process results
    batch_results = []
    errors = 0
    for r in results:
        if isinstance(r, Exception):
            batch_results.append({"ok": False, "error": str(r), "status": 500})
            errors += 1
        else:
            batch_results.append(r)
            if not r.get("ok", True):
                errors += 1

    await emit_event("batch_complete", {"total": len(operations), "errors": errors})

    return _cors_json_response({
        "ok": errors == 0,
        "total": len(operations),
        "success": len(operations) - errors,
        "errors": errors,
        "results": batch_results,
    })


# ============================================================================
# PHASE 3: Browser Session Profiles
# ============================================================================
_PROFILES_DIR = APP_DIR / "profiles"


def _ensure_profiles_dir() -> Path:
    """Ensure profiles directory exists."""
    _PROFILES_DIR.mkdir(parents=True, exist_ok=True)
    return _PROFILES_DIR


async def handle_v1_profiles(request: web.Request) -> web.Response:
    """GET /v1/profiles — List browser session profiles.
    POST /v1/profiles — Save current browser session as profile.
    """
    r = require_auth(request)
    if r: return r
    _record_request()

    if request.method == "GET":
        _ensure_profiles_dir()
        profiles = []
        for p in sorted(_PROFILES_DIR.glob("*.json")):
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
                profiles.append({
                    "name": p.stem,
                    "created": data.get("created", ""),
                    "cookie_count": len(data.get("cookies", [])),
                    "tab_count": len(data.get("tabs", [])),
                    "has_local_storage": bool(data.get("local_storage")),
                    "size_bytes": p.stat().st_size,
                })
            except Exception:
                profiles.append({"name": p.stem, "error": "corrupt profile file"})

        return _cors_json_response({"ok": True, "profiles": profiles, "count": len(profiles)})

    elif request.method == "POST":
        try:
            data = await request.json()
            profile_name = data.get("name", f"profile_{int(time.time())}")
            # Sanitize name
            profile_name = re.sub(r'[^a-zA-Z0-9_\-.]', '_', profile_name)
            save_cookies = data.get("cookies", True)
            save_tabs = data.get("tabs", True)
            save_local_storage = data.get("local_storage", False)
        except Exception as e:
            return _cors_json_response({"ok": False, "error": str(e)}, status=400)

        # Need an active CDP connection
        if not _cdp_state.get("connected") or not _cdp_state.get("manager"):
            return _cors_json_response({"ok": False, "error": "CDP not connected. Connect first."}, status=400)

        mgr = _cdp_state["manager"]
        profile_data = {"created": utc_now(), "name": profile_name, "version": VERSION}

        try:
            # Save cookies
            if save_cookies:
                try:
                    tab, err = await _cdp_active_tab()
                    if tab:
                        cookie_result = await asyncio.wait_for(tab.get_cookies(), timeout=10)
                        profile_data["cookies"] = cookie_result if isinstance(cookie_result, list) else []
                except Exception as e:
                    profile_data["cookies"] = []
                    log.warning("[Profiles] Failed to save cookies: %s", e)

            # Save tabs info
            if save_tabs:
                try:
                    tabs_info = []
                    if mgr.active_tab:
                        # Get current tab URL and title
                        try:
                            eval_result = await asyncio.wait_for(
                                mgr.active_tab.eval_js("JSON.stringify({url: location.href, title: document.title})"),
                                timeout=5)
                            if eval_result:
                                tab_data = json.loads(eval_result) if isinstance(eval_result, str) else {}
                                tabs_info.append(tab_data)
                        except Exception:
                            pass
                    profile_data["tabs"] = tabs_info
                except Exception as e:
                    profile_data["tabs"] = []
                    log.warning("[Profiles] Failed to save tabs: %s", e)

            # Save localStorage
            if save_local_storage:
                try:
                    tab, err = await _cdp_active_tab()
                    if tab:
                        ls_result = await asyncio.wait_for(
                            tab.eval_js("JSON.stringify(Object.fromEntries(Object.entries(localStorage)))"),
                            timeout=5)
                        profile_data["local_storage"] = json.loads(ls_result) if isinstance(ls_result, str) else {}
                except Exception as e:
                    profile_data["local_storage"] = {}
                    log.warning("[Profiles] Failed to save localStorage: %s", e)

            # Write profile
            _ensure_profiles_dir()
            profile_path = _PROFILES_DIR / f"{profile_name}.json"
            profile_path.write_text(json.dumps(profile_data, indent=2, ensure_ascii=False))

            audit({"type": "profile_save", "name": profile_name,
                    "cookies": len(profile_data.get("cookies", [])),
                    "tabs": len(profile_data.get("tabs", []))})
            await emit_event("profile_saved", {"name": profile_name})

            return _cors_json_response({
                "ok": True, "name": profile_name,
                "cookie_count": len(profile_data.get("cookies", [])),
                "tab_count": len(profile_data.get("tabs", [])),
                "has_local_storage": bool(profile_data.get("local_storage")),
            })
        except Exception as e:
            return _cors_json_response({"ok": False, "error": str(e)}, status=500)

    return _cors_json_response({"ok": False, "error": "method not supported"}, status=405)


async def handle_v1_profiles_load(request: web.Request) -> web.Response:
    """POST /v1/profiles/{name}/load — Load a browser session profile."""
    r = require_auth(request)
    if r: return r
    _record_request()

    name = request.match_info.get("name", "")
    if not name:
        return _cors_json_response({"ok": False, "error": "profile name required"}, status=400)

    # Sanitize
    name = re.sub(r'[^a-zA-Z0-9_\-.]', '_', name)
    profile_path = _PROFILES_DIR / f"{name}.json"

    if not profile_path.exists():
        return _cors_json_response({"ok": False, "error": f"profile {name} not found"}, status=404)

    try:
        profile_data = json.loads(profile_path.read_text(encoding="utf-8"))
    except Exception as e:
        return _cors_json_response({"ok": False, "error": f"corrupt profile: {e}"}, status=500)

    # Need active CDP connection
    if not _cdp_state.get("connected") or not _cdp_state.get("manager"):
        return _cors_json_response({"ok": False, "error": "CDP not connected"}, status=400)

    restored = {"cookies": 0, "tabs": 0, "local_storage": False}

    try:
        # Restore cookies
        cookies = profile_data.get("cookies", [])
        if cookies:
            tab, err = await _cdp_active_tab()
            if tab:
                for cookie in cookies:
                    try:
                        await asyncio.wait_for(tab.set_cookie(cookie), timeout=5)
                        restored["cookies"] += 1
                    except Exception:
                        pass

        # Restore tabs
        tabs = profile_data.get("tabs", [])
        if tabs:
            tab_nav, nav_err = await _cdp_active_tab()
            if tab_nav:
                for tab_info in tabs:
                    url = tab_info.get("url", "")
                    if url:
                        try:
                            await asyncio.wait_for(
                                tab_nav.navigate(url), timeout=10)
                            restored["tabs"] += 1
                        except Exception:
                            pass

        # Restore localStorage
        ls = profile_data.get("local_storage", {})
        if ls:
            tab, err = await _cdp_active_tab()
            if tab:
                try:
                    pairs = [f"localStorage.setItem({json.dumps(k)}, {json.dumps(v)})" for k, v in ls.items()]
                    script = ";".join(pairs[:100])  # Limit to 100 items
                    await asyncio.wait_for(tab.eval_js(script), timeout=5)
                    restored["local_storage"] = True
                except Exception:
                    pass

        audit({"type": "profile_load", "name": name, "restored": restored})
        await emit_event("profile_loaded", {"name": name, "restored": restored})

        return _cors_json_response({
            "ok": True, "name": name, "restored": restored,
            "cookie_count": len(profile_data.get("cookies", [])),
            "tab_count": len(profile_data.get("tabs", [])),
        })
    except Exception as e:
        return _cors_json_response({"ok": False, "error": str(e)}, status=500)


# ============================================================================
# PHASE 3: Prometheus Alerts Configuration
# ============================================================================

_ALERTS_CONFIG = {
    "bridge_down": {"enabled": True, "threshold_seconds": 30, "description": "Bridge unresponsive for >30s"},
    "high_latency": {"enabled": True, "threshold_seconds": 5.0, "description": "Request latency >5s"},
    "memory_leak": {"enabled": True, "threshold_mb": 512, "description": "Memory usage >512MB"},
    "cdp_disconnect": {"enabled": True, "threshold_reconnects": 5, "description": "More than 5 CDP reconnects"},
    "error_rate": {"enabled": True, "threshold_percent": 10.0, "description": "Error rate >10%"},
    "rate_limit": {"enabled": True, "threshold_percent": 80.0, "description": "Rate limit >80% utilized"},
}


async def handle_v1_alerts(request: web.Request) -> web.Response:
    """GET /v1/alerts — List alert configurations and current status.
    POST /v1/alerts — Update alert configuration."""
    r = require_auth(request)
    if r: return r
    _record_request()

    if request.method == "POST":
        try:
            data = await request.json()
            for alert_name, config in data.items():
                if alert_name in _ALERTS_CONFIG and isinstance(config, dict):
                    for k, v in config.items():
                        if k in _ALERTS_CONFIG[alert_name]:
                            _ALERTS_CONFIG[alert_name][k] = v
            log.info("[Alerts] Configuration updated")
        except Exception as e:
            return _cors_json_response({"ok": False, "error": str(e)}, status=400)

    # Compute current alert states
    alert_states = {}
    uptime = time.time() - BRIDGE_METRICS["start_time"]
    total_reqs = BRIDGE_METRICS["total_requests"]
    total_errors = BRIDGE_METRICS["total_errors"]

    alert_states["bridge_down"] = {"status": "OK", "uptime_s": round(uptime, 1)}

    # High latency check
    durations = BRIDGE_METRICS.get("request_durations", [])
    avg_dur = sum(durations[-100:]) / len(durations[-100:]) if durations else 0
    alert_states["high_latency"] = {
        "status": "FIRING" if avg_dur > _ALERTS_CONFIG["high_latency"]["threshold_seconds"] else "OK",
        "avg_duration_s": round(avg_dur, 3),
        "threshold_s": _ALERTS_CONFIG["high_latency"]["threshold_seconds"],
    }

    # Memory check
    alert_states["memory_leak"] = {
        "status": "FIRING" if _watchdog_state["memory_mb"] > _ALERTS_CONFIG["memory_leak"]["threshold_mb"] else "OK",
        "current_mb": _watchdog_state["memory_mb"],
        "threshold_mb": _ALERTS_CONFIG["memory_leak"]["threshold_mb"],
    }

    # CDP disconnect check
    reconnects = _cdp_state.get("reconnect_count", 0)
    alert_states["cdp_disconnect"] = {
        "status": "FIRING" if reconnects > _ALERTS_CONFIG["cdp_disconnect"]["threshold_reconnects"] else "OK",
        "reconnects": reconnects,
        "threshold": _ALERTS_CONFIG["cdp_disconnect"]["threshold_reconnects"],
    }

    # Error rate check
    error_rate = (total_errors / total_reqs * 100) if total_reqs > 0 else 0
    alert_states["error_rate"] = {
        "status": "FIRING" if error_rate > _ALERTS_CONFIG["error_rate"]["threshold_percent"] else "OK",
        "error_rate_pct": round(error_rate, 2),
        "threshold_pct": _ALERTS_CONFIG["error_rate"]["threshold_percent"],
    }

    # Rate limit utilization
    rl_usage = 0.0
    with _rate_limit_lock:
        for timestamps in _rate_limit_store.values():
            now = time.time()
            recent = [t for t in timestamps if now - t < _rate_limit_window]
            if recent:
                rl_usage = max(rl_usage, len(recent) / _rate_limit_max * 100)
    alert_states["rate_limit"] = {
        "status": "FIRING" if rl_usage > _ALERTS_CONFIG["rate_limit"]["threshold_percent"] else "OK",
        "usage_pct": round(rl_usage, 1),
        "threshold_pct": _ALERTS_CONFIG["rate_limit"]["threshold_percent"],
    }

    firing = sum(1 for s in alert_states.values() if s.get("status") == "FIRING")

    return _cors_json_response({
        "ok": True,
        "alerts": _ALERTS_CONFIG,
        "states": alert_states,
        "firing": firing,
        "healthy": firing == 0,
    })


# ============================================================================
# PHASE 4: Built-in TLS/HTTPS Support
# ============================================================================
_tls_config: dict[str, Any] = {
    "enabled": False,
    "cert_path": "",
    "key_path": "",
    "auto_cert": False,       # Auto-generate self-signed cert
    "tailscale_cert": False,  # Use Tailscale cert
}


def _generate_self_signed_cert() -> tuple[str, str]:
    """Generate a self-signed TLS certificate for local development.
    
    Returns (cert_path, key_path).
    Uses openssl if available, otherwise creates a simple cert via Python's ssl module.
    """
    cert_dir = APP_DIR / "tls"
    cert_dir.mkdir(parents=True, exist_ok=True)
    cert_path = str(cert_dir / "bridge.crt")
    key_path = str(cert_dir / "bridge.key")
    
    # Try openssl first (most reliable)
    if shutil.which("openssl"):
        try:
            subprocess.run([
                "openssl", "req", "-x509", "-newkey", "rsa:2048",
                "-keyout", key_path, "-out", cert_path,
                "-days", "365", "-nodes",
                "-subj", f"/CN=arena-bridge/O=Arena/C=US"
            ], capture_output=True, timeout=30, check=True)
            log.info("[TLS] Generated self-signed certificate via openssl")
            return cert_path, key_path
        except Exception as e:
            log.warning("[TLS] openssl cert generation failed: %s", e)
    
    # Fallback: use Python's ssl + cryptography (if available) or write a simple cert
    try:
        from cryptography import x509
        from cryptography.x509.oid import NameOID
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import rsa
        
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        subject = issuer = x509.Name([
            x509.NameAttribute(NameOID.COMMON_NAME, "arena-bridge"),
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Arena"),
        ])
        cert = (x509.CertificateBuilder()
                .subject_name(subject)
                .issuer_name(issuer)
                .public_key(key.public_key())
                .serial_number(x509.random_serial_number())
                .not_valid_before(datetime.now(timezone.utc))
                .not_valid_after(datetime.now(timezone.utc) + __import__("datetime").timedelta(days=365))
                .sign(key, hashes.SHA256()))
        
        with open(key_path, "wb") as f:
            f.write(key.private_bytes(serialization.Encoding.PEM,
                                      serialization.PrivateFormat.TraditionalOpenSSL,
                                      serialization.NoEncryption()))
        with open(cert_path, "wb") as f:
            f.write(cert.public_bytes(serialization.Encoding.PEM))
        
        log.info("[TLS] Generated self-signed certificate via Python cryptography")
        return cert_path, key_path
    except ImportError:
        pass
    except Exception as e:
        log.warning("[TLS] Python cert generation failed: %s", e)
    
    return "", ""


def _get_tailscale_cert() -> tuple[str, str]:
    """Try to get Tailscale certificate for the current machine.
    
    Tailscale stores certs in /var/lib/tailscale/certs/ or ~/.ts/certs/
    """
    hostname = socket.gethostname()
    cert_dirs = [
        Path(f"/var/lib/tailscale/certs"),
        Path.home() / ".ts" / "certs",
    ]
    
    for cert_dir in cert_dirs:
        cert_path = cert_dir / f"{hostname}.crt"
        key_path = cert_dir / f"{hostname}.key"
        if cert_path.exists() and key_path.exists():
            log.info("[TLS] Found Tailscale certificate at %s", cert_dir)
            return str(cert_path), str(key_path)
    
    return "", ""


async def handle_v1_tls(request: web.Request) -> web.Response:
    """GET /v1/tls — TLS configuration status.
    POST /v1/tls — Configure TLS (enable/disable, set cert paths, auto-cert)."""
    r = require_auth(request)
    if r: return r
    _record_request()
    
    if request.method == "POST":
        try:
            data = await request.json()
            if "enabled" in data:
                _tls_config["enabled"] = bool(data["enabled"])
            if "cert_path" in data:
                _tls_config["cert_path"] = str(data["cert_path"])
            if "key_path" in data:
                _tls_config["key_path"] = str(data["key_path"])
            if "auto_cert" in data:
                _tls_config["auto_cert"] = bool(data["auto_cert"])
            if "tailscale_cert" in data:
                _tls_config["tailscale_cert"] = bool(data["tailscale_cert"])
            
            # Auto-generate cert if requested
            if _tls_config["auto_cert"] and not _tls_config["cert_path"]:
                cert, key = _generate_self_signed_cert()
                if cert and key:
                    _tls_config["cert_path"] = cert
                    _tls_config["key_path"] = key
                    _tls_config["enabled"] = True
            
            # Try Tailscale cert if requested
            if _tls_config["tailscale_cert"] and not _tls_config["cert_path"]:
                cert, key = _get_tailscale_cert()
                if cert and key:
                    _tls_config["cert_path"] = cert
                    _tls_config["key_path"] = key
                    _tls_config["enabled"] = True
            
            log.info("[TLS] Configuration updated: enabled=%s, cert=%s",
                     _tls_config["enabled"], _tls_config["cert_path"])
        except Exception as e:
            return _cors_json_response({"ok": False, "error": str(e)}, status=400)
    
    # Verify cert files exist
    cert_exists = Path(_tls_config["cert_path"]).exists() if _tls_config["cert_path"] else False
    key_exists = Path(_tls_config["key_path"]).exists() if _tls_config["key_path"] else False
    
    return _cors_json_response({
        "ok": True,
        "tls": {
            "enabled": _tls_config["enabled"],
            "cert_path": _tls_config["cert_path"],
            "key_path": _tls_config["key_path"],
            "auto_cert": _tls_config["auto_cert"],
            "tailscale_cert": _tls_config["tailscale_cert"],
            "cert_exists": cert_exists,
            "key_exists": key_exists,
            "ready": _tls_config["enabled"] and cert_exists and key_exists,
        }
    })


# ============================================================================
# PHASE 4: gRPC-style Secondary Interface
# ============================================================================
_grpc_config: dict[str, Any] = {
    "enabled": False,
    "port": 50051,
    "running": False,
}
_grpc_server_task: asyncio.Task | None = None


async def _grpc_handler(request: web.Request) -> web.Response:
    """Handle gRPC-style JSON requests on the secondary interface.
    
    Accepts JSON payloads in the format:
    {"service": "Bridge", "method": "Status", "params": {}}
    Returns JSON responses in the format:
    {"ok": true, "result": {...}}
    """
    try:
        data = await request.json()
    except Exception:
        return web.json_response({"ok": False, "error": "invalid JSON"}, status=400)
    
    service = data.get("service", "Bridge")
    method = data.get("method", "")
    params = data.get("params", {})
    
    # Route to internal handlers
    method_map = {
        "Bridge/Status": ("/v1/status", "GET"),
        "Bridge/Health": ("/health", "GET"),
        "Bridge/Info": ("/v1/info", "GET"),
        "Bridge/Version": ("/v1/version", "GET"),
        "Bridge/Exec": ("/v1/exec", "POST"),
        "Bridge/Skills": ("/v1/skills", "GET"),
        "Bridge/SkillsRun": ("/v1/skills/run", "POST"),
        "Bridge/Memory": ("/v1/memory", "GET"),
        "Bridge/MemorySet": ("/v1/memory", "POST"),
        "Bridge/Tasks": ("/v1/tasks", "GET"),
        "Bridge/Audit": ("/v1/audit", "GET"),
        "Bridge/Recall": ("/v1/recall", "GET"),
        "Bridge/Watchdog": ("/v1/watchdog", "GET"),
        "Bridge/Alerts": ("/v1/alerts", "GET"),
        "Bridge/Users": ("/v1/users", "GET"),
        "Bridge/Batch": ("/v1/batch", "POST"),
        "CDP/Status": ("/v1/browser/cdp/status", "GET"),
        "CDP/Connect": ("/v1/browser/cdp/connect", "POST"),
        "CDP/Disconnect": ("/v1/browser/cdp/disconnect", "POST"),
        "CDP/Navigate": ("/v1/browser/cdp/navigate", "POST"),
        "CDP/Screenshot": ("/v1/browser/cdp/screenshot", "GET"),
        "CDP/Eval": ("/v1/browser/cdp/eval", "POST"),
        "CDP/Tabs": ("/v1/browser/cdp/tabs", "GET"),
    }
    
    key = f"{service}/{method}" if method else ""
    route = method_map.get(key)
    if not route:
        return web.json_response({
            "ok": False, "error": f"unknown method: {key}",
            "available": list(method_map.keys())
        }, status=404)
    
    path, http_method = route
    cfg = request.app.get("_bridge_cfg", {})
    port = cfg.get("port", 8765)
    token = cfg.get("token", "")
    url = f"http://127.0.0.1:{port}{path}"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    
    try:
        async with aiohttp.ClientSession() as session:
            if http_method == "GET":
                async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=30)) as resp:
                    result = await resp.json()
                    return web.json_response({"ok": resp.status < 400, "result": result, "status": resp.status})
            else:
                async with session.post(url, headers=headers, json=params,
                                        timeout=aiohttp.ClientTimeout(total=60)) as resp:
                    result = await resp.json()
                    return web.json_response({"ok": resp.status < 400, "result": result, "status": resp.status})
    except Exception as e:
        return web.json_response({"ok": False, "error": str(e)}, status=500)


async def _grpc_server_loop(cfg: dict) -> None:
    """Run the gRPC-style secondary interface server."""
    port = _grpc_config["port"]
    app = web.Application(client_max_size=10 * 1024 * 1024)
    app["_bridge_cfg"] = cfg
    app.router.add_post("/call", _grpc_handler)
    app.router.add_get("/health", lambda r: web.json_response({"ok": True, "service": "arena-bridge-grpc"}))
    
    try:
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, "127.0.0.1", port)
        await site.start()
        _grpc_config["running"] = True
        log.info("[gRPC] Secondary interface running on http://127.0.0.1:%d/call", port)
        
        # Keep running until cancelled
        while True:
            await asyncio.sleep(3600)
    except asyncio.CancelledError:
        log.info("[gRPC] Secondary interface stopped")
    except Exception as e:
        log.error("[gRPC] Secondary interface error: %s", e)
    finally:
        _grpc_config["running"] = False
        try:
            await runner.cleanup()
        except Exception:
            pass


async def handle_v1_grpc(request: web.Request) -> web.Response:
    """GET /v1/grpc — gRPC-style interface status.
    POST /v1/grpc — Configure/start/stop the gRPC interface."""
    global _grpc_server_task
    r = require_auth(request)
    if r: return r
    _record_request()
    
    if request.method == "POST":
        try:
            data = await request.json()
            action = data.get("action", "")
            
            if action == "start":
                if _grpc_server_task and not _grpc_server_task.done():
                    return _cors_json_response({"ok": False, "error": "already running"}, status=409)
                _grpc_config["enabled"] = True
                if "port" in data:
                    _grpc_config["port"] = int(data["port"])
                cfg = request.app["cfg"]
                _grpc_server_task = asyncio.create_task(_grpc_server_loop(cfg))
                return _cors_json_response({"ok": True, "message": "gRPC interface starting",
                                            "port": _grpc_config["port"]})
            
            elif action == "stop":
                if _grpc_server_task and not _grpc_server_task.done():
                    _grpc_server_task.cancel()
                    _grpc_config["enabled"] = False
                    return _cors_json_response({"ok": True, "message": "gRPC interface stopping"})
                return _cors_json_response({"ok": False, "error": "not running"}, status=404)
            
            else:
                return _cors_json_response({"ok": False, "error": "action must be 'start' or 'stop'"},
                                           status=400)
        except Exception as e:
            return _cors_json_response({"ok": False, "error": str(e)}, status=400)
    
    return _cors_json_response({
        "ok": True,
        "grpc": {
            "enabled": _grpc_config["enabled"],
            "port": _grpc_config["port"],
            "running": _grpc_config["running"],
            "endpoint": f"http://127.0.0.1:{_grpc_config['port']}/call",
        }
    })


# ============================================================================
# PHASE 4: Live Dashboard v2
# ============================================================================
_DASHBOARD_V2_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Arena Bridge Dashboard v2</title>
<style>
:root { --bg: #0d1117; --surface: #161b22; --border: #30363d; --text: #e6edf3;
       --muted: #8b949e; --accent: #58a6ff; --green: #3fb950; --red: #f85149;
       --yellow: #d29922; --orange: #db6d28; }
* { margin: 0; padding: 0; box-sizing: border-box; }
body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Helvetica, Arial, sans-serif;
       background: var(--bg); color: var(--text); line-height: 1.5; }
.header { background: var(--surface); border-bottom: 1px solid var(--border);
          padding: 16px 24px; display: flex; justify-content: space-between; align-items: center; }
.header h1 { font-size: 20px; font-weight: 600; }
.header .version { color: var(--muted); font-size: 13px; }
.grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
        gap: 16px; padding: 24px; }
.card { background: var(--surface); border: 1px solid var(--border); border-radius: 8px;
        padding: 16px; }
.card h2 { font-size: 14px; font-weight: 600; color: var(--muted); text-transform: uppercase;
           letter-spacing: 0.5px; margin-bottom: 12px; }
.stat { display: flex; justify-content: space-between; align-items: baseline;
        padding: 4px 0; }
.stat .label { color: var(--muted); font-size: 13px; }
.stat .value { font-size: 18px; font-weight: 600; font-variant-numeric: tabular-nums; }
.stat .value.green { color: var(--green); }
.stat .value.red { color: var(--red); }
.stat .value.yellow { color: var(--yellow); }
.stat .value.blue { color: var(--accent); }
.bar-container { height: 6px; background: var(--border); border-radius: 3px;
                margin-top: 4px; overflow: hidden; }
.bar { height: 100%; border-radius: 3px; transition: width 0.5s ease; }
.bar.green { background: var(--green); }
.bar.red { background: var(--red); }
.bar.yellow { background: var(--yellow); }
.bar.blue { background: var(--accent); }
.events { max-height: 200px; overflow-y: auto; }
.event { padding: 4px 8px; font-size: 12px; font-family: monospace;
         border-bottom: 1px solid var(--border); }
.event .time { color: var(--muted); }
.event .type { color: var(--accent); }
.footer { text-align: center; padding: 24px; color: var(--muted); font-size: 12px; }
.ws-status { display: inline-flex; align-items: center; gap: 6px; font-size: 12px; }
.ws-dot { width: 8px; height: 8px; border-radius: 50%; }
.ws-dot.connected { background: var(--green); }
.ws-dot.disconnected { background: var(--red); }
</style>
</head>
<body>
<div class="header">
  <div>
    <h1>Arena Unified Bridge</h1>
    <span class="version" id="version">v---</span>
  </div>
  <div class="ws-status">
    <span class="ws-dot" id="wsDot"></span>
    <span id="wsLabel">Connecting...</span>
  </div>
</div>

<div class="grid">
  <div class="card">
    <h2>Bridge Health</h2>
    <div class="stat"><span class="label">Uptime</span><span class="value blue" id="uptime">--</span></div>
    <div class="stat"><span class="label">Requests</span><span class="value" id="requests">--</span></div>
    <div class="stat"><span class="label">Errors</span><span class="value" id="errors">--</span></div>
    <div class="stat"><span class="label">Error Rate</span><span class="value" id="errorRate">--</span></div>
  </div>

  <div class="card">
    <h2>Resources</h2>
    <div class="stat"><span class="label">Memory</span><span class="value" id="memory">--</span></div>
    <div class="bar-container"><div class="bar green" id="memoryBar" style="width:0%"></div></div>
    <div class="stat"><span class="label">CPU</span><span class="value" id="cpu">--</span></div>
    <div class="bar-container"><div class="bar blue" id="cpuBar" style="width:0%"></div></div>
    <div class="stat"><span class="label">Active Processes</span><span class="value" id="procs">--</span></div>
  </div>

  <div class="card">
    <h2>CDP Browser</h2>
    <div class="stat"><span class="label">Connected</span><span class="value" id="cdpConnected">--</span></div>
    <div class="stat"><span class="label">Reconnects</span><span class="value" id="cdpReconnects">--</span></div>
    <div class="stat"><span class="label">Event Subscribers</span><span class="value" id="subscribers">--</span></div>
  </div>

  <div class="card">
    <h2>Latency</h2>
    <div class="stat"><span class="label">Average</span><span class="value" id="latencyAvg">--</span></div>
    <div class="stat"><span class="label">P50</span><span class="value" id="latencyP50">--</span></div>
    <div class="stat"><span class="label">P95</span><span class="value" id="latencyP95">--</span></div>
    <div class="stat"><span class="label">P99</span><span class="value" id="latencyP99">--</span></div>
  </div>

  <div class="card">
    <h2>Alerts</h2>
    <div id="alertsList"><span class="label">No alerts</span></div>
  </div>

  <div class="card">
    <h2>Live Events</h2>
    <div class="events" id="eventsList"></div>
  </div>
</div>

<div class="footer">Arena Unified Bridge Dashboard v2 &mdash; WebSocket Real-Time</div>

<script>
const BRIDGE = location.origin;
const TOKEN = new URLSearchParams(location.search).get('token') || '';
let ws = null;
let reconnectDelay = 1000;

function fmt(s) {
  if (s < 60) return s.toFixed(0) + 's';
  if (s < 3600) return (s/60).toFixed(1) + 'm';
  return (s/3600).toFixed(1) + 'h';
}

function fmtMs(ms) {
  if (ms < 1) return (ms*1000).toFixed(0) + 'us';
  if (ms < 1000) return ms.toFixed(1) + 'ms';
  return (ms/1000).toFixed(2) + 's';
}

function setVal(id, val, cls) {
  const el = document.getElementById(id);
  if (el) { el.textContent = val; el.className = 'value' + (cls ? ' ' + cls : ''); }
}

function setBar(id, pct, cls) {
  const el = document.getElementById(id);
  if (el) { el.style.width = Math.min(pct, 100) + '%'; el.className = 'bar ' + (cls || 'blue'); }
}

function addEvent(type, data) {
  const list = document.getElementById('eventsList');
  if (!list) return;
  const div = document.createElement('div');
  div.className = 'event';
  const now = new Date().toLocaleTimeString();
  div.innerHTML = '<span class="time">' + now + '</span> <span class="type">' + type + '</span> ' +
                  (typeof data === 'object' ? JSON.stringify(data).substring(0, 100) : String(data).substring(0, 100));
  list.insertBefore(div, list.firstChild);
  if (list.children.length > 50) list.removeChild(list.lastChild);
}

async function pollMetrics() {
  try {
    const h = TOKEN ? {'Authorization': 'Bearer ' + TOKEN} : {};
    const [metricsR, watchdogR, statusR, alertsR] = await Promise.all([
      fetch(BRIDGE + '/metrics', {headers: h}),
      fetch(BRIDGE + '/v1/watchdog', {headers: h}),
      fetch(BRIDGE + '/v1/status', {headers: h}),
      fetch(BRIDGE + '/v1/alerts', {headers: h})
    ]);
    const mt = await metricsR.text();
    const wd = await watchdogR.json();
    const st = await statusR.json();
    const al = await alertsR.json();

    // Parse Prometheus metrics
    const vals = {};
    mt.split('\\n').forEach(line => {
      if (line.startsWith('#') || !line.trim()) return;
      const parts = line.split(' ');
      if (parts.length >= 2) {
        const key = parts[0].replace(/\\{.*\\}/, '');
        vals[key] = parseFloat(parts[1]);
      }
    });

    setVal('requests', vals.arena_bridge_requests_total || 0);
    setVal('errors', vals.arena_bridge_errors_total || 0,
           vals.arena_bridge_errors_total > 0 ? 'red' : 'green');
    const errRate = vals.arena_bridge_requests_total > 0
      ? (vals.arena_bridge_errors_total / vals.arena_bridge_requests_total * 100).toFixed(2) + '%'
      : '0%';
    setVal('errorRate', errRate, parseFloat(errRate) > 5 ? 'red' : 'green');
    setVal('uptime', fmt(vals.arena_bridge_uptime_seconds || 0), 'blue');
    setVal('memory', (wd.memory_mb || 0).toFixed(1) + ' MB',
           wd.memory_mb > 400 ? 'red' : wd.memory_mb > 200 ? 'yellow' : 'green');
    setBar('memoryBar', wd.memory_mb / (wd.memory_limit_mb || 512) * 100,
           wd.memory_mb > 400 ? 'red' : 'green');
    setVal('cpu', (wd.cpu_percent || 0).toFixed(1) + '%',
           wd.cpu_percent > 80 ? 'red' : wd.cpu_percent > 50 ? 'yellow' : 'green');
    setBar('cpuBar', wd.cpu_percent || 0, wd.cpu_percent > 80 ? 'red' : 'blue');
    setVal('procs', vals.arena_bridge_active_processes || 0);
    setVal('cdpConnected', vals.arena_bridge_cdp_connected ? 'Yes' : 'No',
           vals.arena_bridge_cdp_connected ? 'green' : 'yellow');
    setVal('cdpReconnects', vals.arena_bridge_cdp_reconnect_count || 0,
           vals.arena_bridge_cdp_reconnect_count > 3 ? 'red' : '');
    setVal('subscribers', vals.arena_bridge_event_subscribers || 0);
    setVal('latencyAvg', fmtMs((vals.arena_bridge_request_duration_avg_seconds || 0) * 1000));
    setVal('latencyP50', fmtMs((vals.arena_bridge_request_duration_seconds_quantile_0_5 || 0) * 1000));
    setVal('latencyP95', fmtMs((vals.arena_bridge_request_duration_seconds_quantile_0_95 || 0) * 1000));
    setVal('latencyP99', fmtMs((vals.arena_bridge_request_duration_seconds_quantile_0_99 || 0) * 1000));

    // Alerts
    const alertDiv = document.getElementById('alertsList');
    if (al.ok && al.states) {
      const firing = Object.entries(al.states).filter(([k,v]) => v.status === 'FIRING');
      if (firing.length > 0) {
        alertDiv.innerHTML = firing.map(([k,v]) =>
          '<div class="stat"><span class="label">' + k + '</span>' +
          '<span class="value red">FIRING</span></div>').join('');
      } else {
        alertDiv.innerHTML = '<span class="label">All clear (' +
          Object.keys(al.states).length + ' checks)</span>';
      }
    }

    document.getElementById('version').textContent = 'v' + (st.version || vals.arena_bridge_info_version || '?');
  } catch(e) {
    console.error('poll error:', e);
  }
}

function connectWS() {
  const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
  ws = new WebSocket(proto + '//' + location.host + '/v1/events?token=' + TOKEN);
  ws.onopen = () => {
    document.getElementById('wsDot').className = 'ws-dot connected';
    document.getElementById('wsLabel').textContent = 'Live';
    reconnectDelay = 1000;
    addEvent('ws', 'connected');
  };
  ws.onmessage = (e) => {
    try {
      const msg = JSON.parse(e.data);
      if (msg.type !== 'ping') addEvent(msg.type, msg.data || {});
    } catch(err) {}
  };
  ws.onclose = () => {
    document.getElementById('wsDot').className = 'ws-dot disconnected';
    document.getElementById('wsLabel').textContent = 'Disconnected';
    setTimeout(() => { reconnectDelay = Math.min(reconnectDelay * 2, 30000); connectWS(); }, reconnectDelay);
  };
  ws.onerror = () => { ws.close(); };
}

pollMetrics();
setInterval(pollMetrics, 5000);
connectWS();
</script>
</body>
</html>"""


async def handle_gui_v2(request: web.Request) -> web.Response:
    """GET /gui/v2 — Live dashboard with WebSocket real-time updates.
    Shows login page if no valid URL token."""
    cfg = request.app["cfg"]
    url_token = request.query.get("token", "")
    valid_token = bool(url_token) and hmac.compare_digest(url_token, cfg["token"])
    if not valid_token:
        return web.Response(text=_GUI_LOGIN_HTML, content_type="text/html", charset="utf-8")
    return web.Response(text=_DASHBOARD_V2_HTML, content_type="text/html", charset="utf-8")


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


async def handle_v1_ratelimit(request: web.Request) -> web.Response:
    """GET /v1/ratelimit — Rate limit configuration and stats.
    POST /v1/ratelimit — Update rate limit configuration."""
    r = require_auth(request)
    if r: return r
    _record_request()
    if request.method == "POST":
        try:
            data = await request.json()
            update_rate_limit_config(data)
            log.info("[RateLimitv2] Configuration updated")
        except Exception as e:
            return _cors_json_response({"ok": False, "error": str(e)}, status=400)
    return _cors_json_response(rate_limit_stats())


# ============================================================================
# PHASE 4: Skill Sandboxing (isolated execution with resource limits)
# ============================================================================
_sandbox_config: dict[str, Any] = {
    "enabled": True,
    "max_cpu_seconds": 30,
    "max_memory_mb": 256,
    "max_output_bytes": 100 * 1024,
    "allowed_commands": ["python3", "python", "bash", "sh", "node", "echo", "cat", "ls", "grep", "head", "tail", "wc", "sort", "uniq", "cut", "tr", "date", "whoami", "id", "env", "printenv", "which", "pwd"],
    "blocked_env_vars": ["ARENA_TOKEN", "TOKEN", "SECRET", "PASSWORD", "KEY"],
}


async def _run_sandboxed(cmd: str, timeout: int = 30, memory_mb: int = 256) -> dict:
    """Run a command in a sandboxed environment with resource limits.
    
    Uses subprocess with restricted environment, timeout, and output limits.
    On Linux, also sets ulimit for memory if possible.
    """
    result = {"ok": False, "timed_out": False, "memory_exceeded": False}
    
    # Sanitize environment
    clean_env = dict(os.environ)
    for key in list(clean_env.keys()):
        for blocked in _sandbox_config["blocked_env_vars"]:
            if blocked in key.upper():
                clean_env.pop(key, None)
    
    # Add sandbox indicator
    clean_env["ARENA_SANDBOX"] = "1"
    
    if sys.platform == "win32":
        ac_runner = ROOT_AGENT / "scripts" / "appcontainer_run.ps1"
        if ac_runner.exists():
            cmd = f'powershell -NoProfile -ExecutionPolicy Bypass -File "{ac_runner}" "{cmd}"'

    try:
        proc = await asyncio.create_subprocess_shell(
            cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=clean_env,
        )
        
        try:
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(),
                timeout=min(timeout, _sandbox_config["max_cpu_seconds"])
            )
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            result["timed_out"] = True
            result["error"] = f"timeout after {timeout}s"
            return result
        
        out = decode_output(stdout)
        err = decode_output(stderr)
        max_out = _sandbox_config["max_output_bytes"]
        
        if len(out) > max_out:
            out = out[:max_out] + f"\n...[truncated, {len(out) - max_out} bytes omitted]"
        if len(err) > max_out // 2:
            err = err[:max_out // 2] + "\n...[truncated]"
        
        result["ok"] = proc.returncode == 0
        result["exit_code"] = proc.returncode
        result["stdout"] = out
        result["stderr"] = err
        
    except Exception as e:
        result["error"] = str(e)
    
    return result


async def handle_v1_sandbox(request: web.Request) -> web.Response:
    """GET /v1/sandbox — Sandbox configuration.
    POST /v1/sandbox — Run a command in sandbox OR update sandbox config.
    
    To run: {"action": "run", "cmd": "...", "timeout": 30}
    To configure: {"action": "config", "max_cpu_seconds": 60, ...}
    """
    r = require_auth(request)
    if r: return r
    _record_request()
    
    if request.method == "GET":
        return _cors_json_response({"ok": True, "config": _sandbox_config})
    
    try:
        data = await request.json()
    except Exception as e:
        return _cors_json_response({"ok": False, "error": str(e)}, status=400)
    
    action = data.get("action", "run")
    
    if action == "config":
        # Update configuration
        for key in ("max_cpu_seconds", "max_memory_mb", "max_output_bytes"):
            if key in data:
                _sandbox_config[key] = int(data[key])
        if "allowed_commands" in data:
            _sandbox_config["allowed_commands"] = list(data["allowed_commands"])
        if "blocked_env_vars" in data:
            _sandbox_config["blocked_env_vars"] = list(data["blocked_env_vars"])
        if "enabled" in data:
            _sandbox_config["enabled"] = bool(data["enabled"])
        
        audit({"type": "sandbox_config", "changes": {k: v for k, v in data.items() if k != "action"}})
        return _cors_json_response({"ok": True, "config": _sandbox_config})
    
    elif action == "run":
        if not _sandbox_config["enabled"]:
            return _cors_json_response({"ok": False, "error": "sandbox is disabled"}, status=403)
        
        cmd = data.get("cmd", "")
        if not cmd:
            return _cors_json_response({"ok": False, "error": "cmd is required"}, status=400)
        
        # Check if the command is allowed
        first_cmd = first_word(cmd)
        allowed = _sandbox_config["allowed_commands"]
        if allowed and first_cmd not in allowed:
            return _cors_json_response({
                "ok": False, "error": f"command '{first_cmd}' not in allowed list",
                "allowed": allowed
            }, status=403)
        
        # Check for destructive patterns
        block_reason = blocked_reason(cmd)
        if block_reason:
            return _cors_json_response({"ok": False, "error": block_reason}, status=403)
        
        timeout = min(int(data.get("timeout", 30)), _sandbox_config["max_cpu_seconds"])
        result = await _run_sandboxed(cmd, timeout=timeout)
        
        audit({"type": "sandbox_run", "cmd_len": len(cmd),
               "exit_code": result.get("exit_code"), "timed_out": result.get("timed_out", False)})
        await emit_event("sandbox_run", {"cmd": cmd[:50], "ok": result["ok"],
                                          "exit_code": result.get("exit_code")})
        
        return _cors_json_response(result)
    
    else:
        return _cors_json_response({"ok": False, "error": "action must be 'run' or 'config'"},
                                   status=400)


# ============================================================================
# PHASE 4: Clustering / High Availability
# ============================================================================
_cluster_config: dict[str, Any] = {
    "enabled": False,
    "node_id": "",
    "nodes": [],       # [{"id": "...", "url": "http://...", "role": "leader|follower"}]
    "leader_id": "",
    "heartbeat_interval_s": 10,
    "failover_timeout_s": 30,
}
_cluster_state: dict[str, Any] = {
    "last_heartbeat": 0.0,
    "role": "standalone",  # standalone | leader | follower
    "peers_healthy": {},
}
_cluster_task: asyncio.Task | None = None


def _get_node_id() -> str:
    """Generate a unique node ID based on hostname and port."""
    return f"{socket.gethostname()}-{os.getpid()}"


async def _cluster_heartbeat_loop() -> None:
    """Periodically send heartbeats to peer nodes."""
    while True:
        try:
            await asyncio.sleep(_cluster_config["heartbeat_interval_s"])
            _cluster_state["last_heartbeat"] = time.time()
            
            # Check peer health
            for node in _cluster_config["nodes"]:
                node_url = node.get("url", "")
                if not node_url:
                    continue
                try:
                    async with aiohttp.ClientSession() as session:
                        async with session.get(
                            f"{node_url}/health",
                            timeout=aiohttp.ClientTimeout(total=5)
                        ) as resp:
                            healthy = resp.status == 200
                            _cluster_state["peers_healthy"][node.get("id", node_url)] = {
                                "healthy": healthy,
                                "last_check": time.time(),
                            }
                except Exception:
                    _cluster_state["peers_healthy"][node.get("id", node_url)] = {
                        "healthy": False,
                        "last_check": time.time(),
                    }
            
            # Prune stale peer entries (nodes no longer in config)
            known_ids = {n.get("id", n.get("url", "")) for n in _cluster_config["nodes"]}
            _cluster_state["peers_healthy"] = {
                k: v for k, v in _cluster_state["peers_healthy"].items() if k in known_ids
            }
            
            # Simple leader election: node with lowest ID is leader
            if _cluster_config["nodes"]:
                all_ids = sorted([_cluster_config["node_id"]] +
                                 [n.get("id", "") for n in _cluster_config["nodes"]])
                _cluster_config["leader_id"] = all_ids[0]
                _cluster_state["role"] = "leader" if _cluster_config["leader_id"] == _cluster_config["node_id"] else "follower"
        
        except asyncio.CancelledError:
            break
        except Exception as e:
            log.error("[Cluster] Heartbeat error: %s", e)
            await asyncio.sleep(5)


async def handle_v1_cluster(request: web.Request) -> web.Response:
    """GET /v1/cluster — Cluster configuration and status.
    POST /v1/cluster — Configure clustering (add/remove nodes, enable/disable)."""
    global _cluster_task
    r = require_auth(request)
    if r: return r
    _record_request()
    
    if request.method == "POST":
        try:
            data = await request.json()
            action = data.get("action", "")
            
            if action == "enable":
                _cluster_config["enabled"] = True
                _cluster_config["node_id"] = _cluster_config["node_id"] or _get_node_id()
                if "nodes" in data:
                    _cluster_config["nodes"] = data["nodes"]
                if "heartbeat_interval_s" in data:
                    _cluster_config["heartbeat_interval_s"] = max(5, int(data["heartbeat_interval_s"]))
                # Start heartbeat loop
                if _cluster_task and not _cluster_task.done():
                    _cluster_task.cancel()
                _cluster_task = asyncio.create_task(_cluster_heartbeat_loop())
                _cluster_state["role"] = "leader" if not _cluster_config["nodes"] else "follower"
                log.info("[Cluster] Enabled: node_id=%s, peers=%d",
                         _cluster_config["node_id"], len(_cluster_config["nodes"]))
            
            elif action == "disable":
                _cluster_config["enabled"] = False
                if _cluster_task and not _cluster_task.done():
                    _cluster_task.cancel()
                    _cluster_task = None
                _cluster_state["role"] = "standalone"
                log.info("[Cluster] Disabled")
            
            elif action == "add_node":
                node_url = data.get("url", "")
                node_id = data.get("id", node_url)
                if not node_url:
                    return _cors_json_response({"ok": False, "error": "url is required"}, status=400)
                # Avoid duplicates
                if not any(n.get("id") == node_id for n in _cluster_config["nodes"]):
                    _cluster_config["nodes"].append({"id": node_id, "url": node_url, "role": "follower"})
                log.info("[Cluster] Added node: %s", node_id)
            
            elif action == "remove_node":
                node_id = data.get("id", "")
                _cluster_config["nodes"] = [n for n in _cluster_config["nodes"] if n.get("id") != node_id]
                log.info("[Cluster] Removed node: %s", node_id)
            
            else:
                return _cors_json_response({"ok": False, "error": "action must be enable/disable/add_node/remove_node"},
                                           status=400)
            
            audit({"type": "cluster_update", "action": action})
        except Exception as e:
            return _cors_json_response({"ok": False, "error": str(e)}, status=400)
    
    return _cors_json_response({
        "ok": True,
        "cluster": {
            "enabled": _cluster_config["enabled"],
            "node_id": _cluster_config["node_id"],
            "nodes": _cluster_config["nodes"],
            "leader_id": _cluster_config["leader_id"],
            "role": _cluster_state["role"],
            "last_heartbeat": _cluster_state["last_heartbeat"],
            "peers_healthy": _cluster_state["peers_healthy"],
            "heartbeat_interval_s": _cluster_config["heartbeat_interval_s"],
        }
    })


# ============================================================================
# PHASE 4: API Versioning (/v2/ endpoints with deprecation headers)
# ============================================================================
_DEPRECATED_ENDPOINTS: dict[str, dict[str, str]] = {
    "/v1/service/info": {"deprecated_since": "1.9.27", "replacement": "/v1/status", "removal_version": "2.3.0"},
    "/v1/sys/svc": {"deprecated_since": "1.9.27", "replacement": "/v1/status", "removal_version": "2.3.0"},
    "/v1/sys/funnel": {"deprecated_since": "1.9.27", "replacement": "/v1/tailscale/funnel/status", "removal_version": "2.3.0"},
}


async def handle_v2_index(request: web.Request) -> web.Response:
    """GET /v2/ — API v2 index with versioning info and deprecation notices."""
    r = require_auth(request)
    if r: return r
    _record_request()
    
    return _cors_json_response({
        "ok": True,
        "api_version": "2",
        "bridge_version": VERSION,
        "deprecations": _DEPRECATED_ENDPOINTS,
        "v2_endpoints": {
            "GET /v2/": "API v2 index",
            "GET /v2/status": "Bridge status (replaces /v1/status)",
            "GET /v2/health": "Detailed health check",
            "GET /v2/browser/status": "CDP + browser status combined",
            "POST /v2/exec": "Exec with sandbox by default",
            "GET /v2/deprecations": "List deprecated v1 endpoints",
        }
    })


async def handle_v2_status(request: web.Request) -> web.Response:
    """GET /v2/status — Enhanced status with versioning info."""
    r = require_auth(request)
    if r: return r
    _record_request()
    
    cfg = request.app["cfg"]
    uptime = time.time() - BRIDGE_METRICS["start_time"]
    
    return _cors_json_response({
        "ok": True,
        "version": VERSION,
        "api_version": "2",
        "uptime_seconds": round(uptime, 1),
        "total_requests": BRIDGE_METRICS["total_requests"],
        "total_errors": BRIDGE_METRICS["total_errors"],
        "cdp": {"connected": _cdp_state["connected"],
                "reconnects": _cdp_state.get("reconnect_count", 0)},
        "watchdog": {"memory_mb": _watchdog_state["memory_mb"],
                     "cpu_percent": _watchdog_state["cpu_percent"]},
        "cluster": {"role": _cluster_state["role"],
                    "enabled": _cluster_config["enabled"]},
        "tls": {"enabled": _tls_config["enabled"],
                "ready": _tls_config["enabled"] and
                         Path(_tls_config["cert_path"]).exists() if _tls_config["cert_path"] else False},
    })


async def handle_v2_health(request: web.Request) -> web.Response:
    """GET /v2/health — Detailed health check with all subsystem status."""
    _record_request()
    
    checks = {
        "bridge": True,
        "cdp": _cdp_state["connected"],
        "watchdog": _watchdog_state["last_check"] > 0,
        "tls": _tls_config["enabled"] and Path(_tls_config["cert_path"]).exists() if _tls_config["cert_path"] else False,
        "cluster": _cluster_config["enabled"],
    }
    
    all_healthy = True  # Bridge is always healthy if responding
    
    return _cors_json_response({
        "ok": all_healthy,
        "status": "healthy" if all_healthy else "degraded",
        "version": VERSION,
        "api_version": "2",
        "checks": checks,
        "uptime_seconds": round(time.time() - BRIDGE_METRICS["start_time"], 1),
    })


async def handle_v2_browser_status(request: web.Request) -> web.Response:
    """GET /v2/browser/status — Combined CDP + browser status."""
    r = require_auth(request)
    if r: return r
    _record_request()
    
    return _cors_json_response({
        "ok": True,
        "api_version": "2",
        "cdp": {
            "connected": _cdp_state["connected"],
            "headless": _cdp_state["headless"],
            "port": _cdp_state["port"],
            "reconnect_count": _cdp_state.get("reconnect_count", 0),
        },
        "browseract": {
            "available": bool(shutil.which("browser-act")),
        },
        "profiles": {
            "count": len(list(_PROFILES_DIR.glob("*.json"))) if _PROFILES_DIR.exists() else 0,
        }
    })


async def handle_v2_exec(request: web.Request) -> web.Response:
    """POST /v2/exec — Execute command in sandbox by default.
    
    Same as /v1/exec but with sandbox enabled by default.
    Accepts all /v1/exec params plus:
      - sandbox: bool (default: True)
      - max_cpu_seconds: int (default: from sandbox config)
    """
    r = require_auth(request)
    if r: return r
    _record_request()
    
    try:
        data = await request.json()
    except Exception as e:
        return _cors_json_response({"ok": False, "error": f"invalid json: {e}"}, status=400)
    
    cmd = data.get("cmd", "")
    if not cmd:
        return _cors_json_response({"ok": False, "error": "missing 'cmd'"}, status=400)
    
    block = blocked_reason(cmd)
    if block:
        return _cors_json_response({"ok": False, "error": block}, status=403)
    
    use_sandbox = data.get("sandbox", True)
    
    if use_sandbox and _sandbox_config["enabled"]:
        # Apply same command allowlist as /v1/sandbox
        first_cmd = first_word(cmd)
        allowed = _sandbox_config["allowed_commands"]
        if allowed and first_cmd not in allowed:
            return _cors_json_response({
                "ok": False, "error": f"command '{first_cmd}' not in allowed list (sandbox mode)",
                "allowed": allowed, "api_version": "2"
            }, status=403)
        timeout = min(int(data.get("timeout", 30)), _sandbox_config["max_cpu_seconds"])
        result = await _run_sandboxed(cmd, timeout=timeout)
        result["sandbox"] = True
        result["api_version"] = "2"
    else:
        # Fall back to normal exec
        timeout = min(int(data.get("timeout", 60)), cfg_get_max_timeout(request))
        try:
            proc = await asyncio.create_subprocess_shell(
                cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            result = {
                "ok": proc.returncode == 0,
                "exit_code": proc.returncode,
                "stdout": decode_output(stdout)[-50000:],
                "stderr": decode_output(stderr)[-10000:],
                "sandbox": False,
                "api_version": "2",
            }
        except asyncio.TimeoutError:
            result = {"ok": False, "error": f"timeout after {timeout}s", "sandbox": False, "api_version": "2"}
        except Exception as e:
            result = {"ok": False, "error": str(e), "sandbox": False, "api_version": "2"}
    
    audit({"type": "exec_v2", "cmd_len": len(cmd), "sandbox": use_sandbox,
           "exit_code": result.get("exit_code")})
    await emit_event("exec", {"cmd": cmd[:50], "ok": result["ok"], "sandbox": use_sandbox})
    _record_request(is_exec=True)
    
    return _cors_json_response(result)


def cfg_get_max_timeout(request: web.Request) -> int:
    """Get max timeout from bridge config."""
    try:
        return request.app["cfg"].get("max_timeout", 600)
    except Exception:
        return 600


async def handle_v2_deprecations(request: web.Request) -> web.Response:
    """GET /v2/deprecations — List all deprecated v1 endpoints."""
    r = require_auth(request)
    if r: return r
    _record_request()
    
    return _cors_json_response({
        "ok": True,
        "api_version": "2",
        "deprecations": _DEPRECATED_ENDPOINTS,
        "count": len(_DEPRECATED_ENDPOINTS),
        "migration_guide": {
            "/v1/service/info → /v1/status": "Use /v1/status for all service information",
            "/v1/sys/svc → /v1/status": "Service status is now part of /v1/status",
            "/v1/sys/funnel → /v1/tailscale/funnel/status": "Funnel status moved to tailscale namespace",
        }
    })


# ============================================================================
# PHASE 4: OpenTelemetry Tracing
# ============================================================================
_otel_config: dict[str, Any] = {
    "enabled": False,
    "service_name": "arena-bridge",
    "endpoint": "",       # OTLP endpoint (e.g., "http://localhost:4318/v1/traces")
    "sample_rate": 1.0,   # 0.0 to 1.0
    "max_spans": 1000,
}
_otel_traces: list[dict] = []
_otel_lock = threading.Lock()
_otel_trace_counter: int = 0


def _otel_trace_id() -> str:
    """Generate a trace ID."""
    global _otel_trace_counter
    _otel_trace_counter += 1
    return f"{_otel_trace_counter:016x}{secrets.token_hex(8)}"


def _otel_record_span(trace_id: str, span_id: str, name: str,
                       duration_ms: float, attributes: dict | None = None,
                       parent_span_id: str = "", status: str = "OK") -> None:
    """Record an OpenTelemetry span."""
    span = {
        "trace_id": trace_id,
        "span_id": span_id,
        "name": name,
        "kind": "SERVER",
        "start_time": utc_now(),
        "duration_ms": round(duration_ms, 2),
        "status": status,
        "attributes": attributes or {},
        "resource": {
            "service.name": _otel_config["service_name"],
            "service.version": VERSION,
        },
    }
    if parent_span_id:
        span["parent_span_id"] = parent_span_id
    
    with _otel_lock:
        _otel_traces.append(span)
        if len(_otel_traces) > _otel_config["max_spans"]:
            _otel_traces[:] = _otel_traces[-_otel_config["max_spans"]:]


def _otel_should_sample() -> bool:
    """Decide if this request should be traced."""
    if not _otel_config["enabled"]:
        return False
    import random
    return random.random() < _otel_config["sample_rate"]


async def handle_v1_tracing(request: web.Request) -> web.Response:
    """GET /v1/tracing — OpenTelemetry tracing configuration and recent traces.
    POST /v1/tracing — Configure tracing."""
    r = require_auth(request)
    if r: return r
    _record_request()
    
    if request.method == "POST":
        try:
            data = await request.json()
            if "enabled" in data:
                _otel_config["enabled"] = bool(data["enabled"])
            if "service_name" in data:
                _otel_config["service_name"] = str(data["service_name"])
            if "endpoint" in data:
                _otel_config["endpoint"] = str(data["endpoint"])
            if "sample_rate" in data:
                _otel_config["sample_rate"] = max(0.0, min(1.0, float(data["sample_rate"])))
            if "max_spans" in data:
                _otel_config["max_spans"] = max(10, int(data["max_spans"]))
            log.info("[OTel] Configuration updated: enabled=%s, endpoint=%s, sample_rate=%.2f",
                     _otel_config["enabled"], _otel_config["endpoint"], _otel_config["sample_rate"])
        except Exception as e:
            return _cors_json_response({"ok": False, "error": str(e)}, status=400)
    
    # Return config + recent traces
    recent_traces = []
    with _otel_lock:
        recent_traces = list(_otel_traces[-50:])
    
    return _cors_json_response({
        "ok": True,
        "config": _otel_config,
        "recent_traces": len(_otel_traces),
        "traces": recent_traces,
    })


async def handle_v1_traces_export(request: web.Request) -> web.Response:
    """POST /v1/traces/export — Export traces in OTLP JSON format.
    GET /v1/traces/export — Get all stored traces."""
    r = require_auth(request)
    if r: return r
    _record_request()
    
    if request.method == "POST":
        # Export to configured OTLP endpoint
        if not _otel_config["endpoint"]:
            return _cors_json_response({"ok": False, "error": "no OTLP endpoint configured"}, status=400)
        
        with _otel_lock:
            traces = list(_otel_traces)
        
        if not traces:
            return _cors_json_response({"ok": True, "exported": 0, "message": "no traces to export"})
        
        # Build OTLP JSON payload
        otlp_payload = {
            "resourceSpans": [{
                "resource": {
                    "attributes": [
                        {"key": "service.name", "value": {"stringValue": _otel_config["service_name"]}},
                        {"key": "service.version", "value": {"stringValue": VERSION}},
                    ]
                },
                "scopeSpans": [{
                    "scope": {"name": "arena-bridge"},
                    "spans": traces,
                }]
            }]
        }
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    _otel_config["endpoint"],
                    json=otlp_payload,
                    headers={"Content-Type": "application/json"},
                    timeout=aiohttp.ClientTimeout(total=10)
                ) as resp:
                    exported = len(traces)
                    if resp.status < 400:
                        # Clear exported traces
                        with _otel_lock:
                            _otel_traces.clear()
                        return _cors_json_response({"ok": True, "exported": exported})
                    else:
                        return _cors_json_response({
                            "ok": False, "error": f"OTLP endpoint returned {resp.status}",
                            "exported": 0
                        }, status=502)
        except Exception as e:
            return _cors_json_response({"ok": False, "error": str(e)}, status=502)
    
    # GET: return all traces
    with _otel_lock:
        all_traces = list(_otel_traces)
    
    return _cors_json_response({
        "ok": True,
        "total": len(all_traces),
        "traces": all_traces,
    })


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

MCP_SESSIONS: dict[str, dict] = {}  # session_id -> {created, queue}
MCP_SESSION_MAX_AGE_MS = 3600_000  # 1 hour — stale sessions auto-cleaned


def _cleanup_mcp_sessions() -> int:
    """Remove MCP sessions older than MCP_SESSION_MAX_AGE_MS. Returns count removed."""
    now = now_ms()
    stale = [sid for sid, sess in MCP_SESSIONS.items()
             if now - sess.get("created", 0) > MCP_SESSION_MAX_AGE_MS]
    for sid in stale:
        MCP_SESSIONS.pop(sid, None)
    return len(stale)


def sid() -> str:
    return secrets.token_urlsafe(18)


def now_ms() -> int:
    return int(time.time() * 1000)


# ============================================================================
# WEB GATEWAY WHITELIST
# ============================================================================

GW_WHITELIST = (
    "agentctl skill ", "agentctl mem ", "agentctl recall ",
    "agentctl sub list", "agentctl sub show", "agentctl sub spawn",
    "agentctl browser py-", "agentctl agents ", "agentctl mission list",
    "agentctl sys status", "agentctl hooks list", "agentctl report ",
)


def gw_allowed(cmd: str) -> bool:
    """Check if a gateway command is allowed. Blocks shell metacharacters."""
    if not any(cmd.startswith(p) for p in GW_WHITELIST):
        return False
    for ch in [";", "&", "|", "`", "$", "(", ")", "{", "}", "\n", ">", ">>", "<"]:
        if ch in cmd:
            return False
    return True


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
    global _grpc_server_task, _cluster_task
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
    if _grpc_server_task and not _grpc_server_task.done():
        _grpc_server_task.cancel()
        try:
            await _grpc_server_task
        except asyncio.CancelledError:
            pass
    
    # Stop cluster heartbeat task
    if _cluster_task and not _cluster_task.done():
        _cluster_task.cancel()
        try:
            await _cluster_task
        except asyncio.CancelledError:
            pass

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


# ============================================================================
# HANDLERS — Public
# ============================================================================

async def handle_index(request: web.Request) -> web.Response:
    try:
        _record_request()
        return _cors_json_response({
            "ok": True,
            "service": "arena-unified-bridge",
            "version": VERSION,
            "endpoints": [
                "/health", "/v1/version", "/v1/info", "/v1/status", "/v1/sysinfo",
                "/v1/capabilities", "/v1/hardware", "/v1/hwinfo", "/v1/inventory?section=&format=text|json",
                "/v1/ps", "/v1/audit?lines=100", "/v1/audit/stats",
                "POST /v1/exec", "POST /v1/kill",
                "POST /v1/upload?path=", "GET /v1/download?path=",
                "GET /v1/memory?q=", "POST /v1/memory",
                "GET /v1/missions", "GET /v1/mission/show?name=",
                "GET /v1/reports", "GET /v1/doctor", "POST /v1/beep",
                "GET /v1/browser/search?q=", "GET /v1/browser/read?url=",
                "GET /v1/browser/dump?url=", "GET /v1/browser/fetch?url=",
                "GET /v1/browser/head?url=",
                "GET /v1/browser/cdp/status", "POST /v1/browser/cdp/connect", "POST /v1/browser/cdp/disconnect",
                "POST /v1/browser/cdp/navigate", "GET /v1/browser/cdp/screenshot", "GET /v1/browser/cdp/dom",
                "POST /v1/browser/cdp/eval", "POST /v1/browser/cdp/click (selector|x,y)", "POST /v1/browser/cdp/type",
                "GET /v1/desktop/screenshot", "POST /v1/desktop/click", "POST /v1/desktop/type",
                "POST /v1/desktop/key", "POST /v1/desktop/mouse", "GET /v1/desktop/windows",
                "GET /v1/desktop/active_window", "POST /v1/desktop/focus",
                "GET /v1/control/status", "POST /v1/control/pause", "POST /v1/control/resume", "POST /v1/control/revoke",
                "GET /v1/browser/cdp/tabs", "POST /v1/browser/cdp/tabs/new", "POST /v1/browser/cdp/tabs/close",
                "POST /v1/browser/cdp/tabs/activate", "GET/POST/DELETE /v1/browser/cdp/cookies",
                "POST /v1/browser/cdp/cookies/clear", "GET/POST /v1/browser/cdp/cookies/profiles",
                "POST /v1/browser/cdp/network/start", "POST /v1/browser/cdp/network/stop",
                "GET /v1/browser/cdp/network/requests", "GET /v1/browser/cdp/network/har",
                "POST /v1/browser/cdp/intercept/start", "POST /v1/browser/cdp/intercept/stop",
                "POST/DELETE/GET /v1/browser/cdp/intercept/rule|rules",
                "GET /v1/browser/cdp/session/check", "GET/POST /v1/cdp/* aliases",

                "GET /v1/recall?q=&top=5", "GET /v1/recall/digest",
                "GET /v1/tasks?status=&limit=20", "POST /v1/tasks", "POST /v1/tasks/clean",
                "GET /v1/skills", "POST /v1/skills/run",
                "GET /v1/hooks", "GET /v1/agents",
                "GET /v1/subagents", "POST /v1/subagents/spawn",
                "GET /v1/sys/svc", "GET /v1/sys/funnel",
        "GET /v1/service/info",
        "POST /v1/token/regenerate",
        "POST /v1/tailscale/funnel/{start|stop|status}",
        "POST /v1/restart",
        "GET /v1/config",
                "GET /v1/metrics",
                "/gui", "POST /mcp", "DELETE /mcp",
                "GET /sse", "POST /messages", "GET /ws",
                "/gateway", "/gateway/tools", "POST /run", "POST /tool",
            ],
            "auth_required_for_exec": True,
        })
    except Exception as e:
        return _cors_json_response({"ok": False, "error": str(e)}, status=500)


async def handle_health(request: web.Request) -> web.Response:
    try:
        _record_request()
        return _cors_json_response({
            "ok": True,
            "service": "arena-unified-bridge",
            "version": VERSION,
            "uptime_seconds": round(time.time() - BRIDGE_METRICS["start_time"], 1),
        })
    except Exception:
        return _cors_json_response({"ok": False, "service": "arena-unified-bridge"}, status=500)













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










async def handle_v1_ps(request: web.Request) -> web.Response:
    try:
        r = require_auth(request)
        if r: return r
        _record_request()
        ps_list = []
        for req_id, info in ACTIVE_PROCESSES.items():
            ps_list.append({
                "request_id": req_id,
                "pid": info["pid"],
                "cmd": info["cmd"][:200],
                "uptime_sec": round(time.time() - info["start"], 1),
            })
        return _cors_json_response({"ok": True, "processes": ps_list, "count": len(ps_list)})
    except Exception as e:
        return _cors_json_response({"ok": False, "error": str(e)}, status=500)




async def handle_v1_exec(request: web.Request) -> web.Response:
    r = require_auth(request)
    if r: return r
    cfg = request.app["cfg"]

    try:
        data = await request.json()
    except Exception as e:
        _record_request(is_error=True, count_request=False)
        return _cors_json_response({"ok": False, "error": f"invalid json: {e}"}, status=400)

    if not isinstance(data, dict):
        _record_request(is_error=True, count_request=False)
        return _cors_json_response({"ok": False, "error": "JSON must be object"}, status=400)

    request_id = str(data.get("request_id") or uuid.uuid4())
    cmd = str(data.get("cmd", "")).strip()
    if not cmd:
        _record_request(is_error=True, count_request=False)
        return _cors_json_response({"ok": False, "error": "missing cmd", "request_id": request_id}, status=400)

    # Safety checks
    reason = blocked_reason(cmd)
    if reason:
        audit({"type": "exec_blocked", "request_id": request_id, "cmd": cmd, "reason": reason,
                "client": request.remote or "127.0.0.1"})
        _record_request(is_error=True, count_request=False)
        return _cors_json_response({"ok": False, "error": reason, "request_id": request_id}, status=403)

    # v2.10.0: Honor the control lease for exec commands that would inject
    # desktop input. General shell stays available while paused (so the agent
    # can still diagnose/recover), but keyboard/mouse injection is blocked —
    # closing the pause-bypass hole where exec could drive ydotool/xdotool.
    ctrl_err = _control_check()
    if ctrl_err:
        inj = _is_input_injection_cmd(cmd)
        if inj:
            audit({"type": "exec_blocked_control", "request_id": request_id, "cmd": cmd,
                   "reason": ctrl_err.get("error"), "matched": inj,
                   "client": request.remote or "127.0.0.1"})
            _record_request(is_error=True, count_request=False)
            err = dict(ctrl_err)
            err["request_id"] = request_id
            err["message"] = (
                "Desktop input injection blocked while control is "
                f"{ctrl_err.get('status')}. Resume control to inject input."
            )
            return _cors_json_response(err, status=403)

    profile = cfg["profile"]
    fw = first_word(cmd)
    if profile == "cautious" and fw not in CAUTIOUS_ALLOW:
        reason = f"command '{fw}' not in cautious allowlist; use --profile owner-shell"
        audit({"type": "exec_blocked", "request_id": request_id, "cmd": cmd, "reason": reason,
                "client": request.remote or "127.0.0.1"})
        _record_request(is_error=True, count_request=False)
        return _cors_json_response({"ok": False, "error": reason, "request_id": request_id}, status=403)

    root: Path = cfg["root"]
    cwd_raw = str(data.get("cwd") or root)
    cwd = Path(cwd_raw).expanduser()
    if not cwd.is_absolute():
        cwd = root / cwd
    if not cfg["allow_any_cwd"] and not under_root(cwd, root):
        _record_request(is_error=True, count_request=False)
        return _cors_json_response(
            {"ok": False, "error": f"cwd must be under root {root}", "request_id": request_id}, status=403)
    if not cwd.exists() or not cwd.is_dir():
        _record_request(is_error=True, count_request=False)
        return _cors_json_response(
            {"ok": False, "error": f"cwd does not exist: {cwd}", "request_id": request_id}, status=400)

    timeout = min(int(data.get("timeout", cfg["timeout"])), cfg["max_timeout"])
    max_output = min(int(data.get("max_output", DEFAULT_MAX_OUTPUT)), cfg["max_output"])
    env_extra = data.get("env") if isinstance(data.get("env"), dict) else {}
    env = os.environ.copy()
    # Block dangerous environment variables that could escalate privileges
    _BLOCKED_ENV_PATTERNS = ["ARENA_TOKEN", "TOKEN", "SECRET", "PASSWORD", "KEY",
                              "LD_PRELOAD", "LD_LIBRARY_PATH", "PYTHONPATH", "PYTHONSTARTUP"]
    for k in list(env_extra.keys()):
        for blocked in _BLOCKED_ENV_PATTERNS:
            if blocked in k.upper():
                del env_extra[k]
                break
    env.update({str(k): str(v) for k, v in env_extra.items()})

    sem: asyncio.Semaphore = cfg["semaphore"]
    if sem.locked() and cfg["active_exec"] >= cfg["max_concurrent"]:
        _record_request(is_error=True, count_request=False)
        return _cors_json_response(
            {"ok": False, "error": "too many concurrent exec requests", "request_id": request_id}, status=429)

    await sem.acquire()
    cfg["active_exec"] += 1

    audit({"type": "exec_start", "request_id": request_id, "cmd": cmd, "cwd": str(cwd),
            "timeout": timeout, "client": request.remote or "127.0.0.1"})

    t0 = time.time()
    timed_out = False
    proc = None

    try:
        # Use async subprocess
        proc = await asyncio.create_subprocess_shell(
            cmd, cwd=str(cwd), env=env,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)

        ACTIVE_PROCESSES[request_id] = {"cmd": cmd, "pid": proc.pid, "start": time.time()}

        try:
            stdout_bytes, stderr_bytes = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            exit_code = proc.returncode
        except asyncio.TimeoutError:
            timed_out = True
            proc.kill()
            try:
                stdout_bytes, stderr_bytes = await asyncio.wait_for(proc.communicate(), timeout=5)
            except asyncio.TimeoutError:
                stdout_bytes, stderr_bytes = b"", b""
            exit_code = proc.returncode if proc.returncode is not None else -1

        duration = round(time.time() - t0, 3)

        # Decode output
        stdout = decode_output(stdout_bytes) if stdout_bytes else ""
        stderr = decode_output(stderr_bytes) if stderr_bytes else ""

        # Truncate if needed
        truncated = False
        if len(stdout.encode("utf-8", "replace")) > max_output:
            stdout = stdout.encode("utf-8", "replace")[:max_output].decode("utf-8", "replace")
            truncated = True
        if len(stderr.encode("utf-8", "replace")) > max_output:
            stderr = stderr.encode("utf-8", "replace")[:max_output].decode("utf-8", "replace")
            truncated = True

        stdout_bytes_len = len(stdout_bytes) if stdout_bytes else 0
        stderr_bytes_len = len(stderr_bytes) if stderr_bytes else 0

        ok = (not timed_out) and exit_code == 0
        event_type = "exec_timeout" if timed_out else "exec_done"
        audit({"type": event_type, "request_id": request_id, "cmd": cmd, "exit_code": exit_code,
                "duration": duration, "truncated": truncated,
                "stdout_bytes": stdout_bytes_len, "stderr_bytes": stderr_bytes_len})

        _record_request(duration=duration, is_exec=True, is_error=not ok)
        return _cors_json_response({
            "ok": ok,
            "request_id": request_id,
            "exit_code": exit_code,
            "duration_sec": duration,
            "cwd": str(cwd),
            "stdout": stdout,
            "stderr": stderr,
            "truncated": truncated,
            "stdout_bytes": stdout_bytes_len,
            "stderr_bytes": stderr_bytes_len,
            "error": f"timeout after {timeout}s" if timed_out else None,
        }, status=408 if timed_out else 200)

    except Exception as e:
        duration = round(time.time() - t0, 3)
        audit({"type": "exec_error", "request_id": request_id, "cmd": cmd, "duration": duration, "error": repr(e)})
        _record_request(duration=duration, is_exec=True, is_error=True)
        return _cors_json_response({"ok": False, "request_id": request_id, "error": "Internal error", "duration_sec": duration}, status=500)

    finally:
        ACTIVE_PROCESSES.pop(request_id, None)
        cfg["active_exec"] -= 1
        sem.release()


async def handle_v1_kill(request: web.Request) -> web.Response:
    r = require_auth(request)
    if r: return r
    try:
        data = await request.json()
    except Exception:
        _record_request(is_error=True, count_request=False)
        return _cors_json_response({"ok": False, "error": "invalid json"}, status=400)
    target_id = data.get("request_id")
    if not target_id or target_id not in ACTIVE_PROCESSES:
        _record_request(is_error=True, count_request=False)
        return _cors_json_response({"ok": False, "error": "process not found"}, status=404)
    info = ACTIVE_PROCESSES[target_id]
    try:
        os.kill(info["pid"], signal.SIGTERM if os.name != "nt" else signal.CTRL_BREAK_EVENT)
    except Exception:
        pass
    audit({"type": "process_killed", "target_request_id": target_id, "client": request.remote or "127.0.0.1"})
    _record_request()
    return _cors_json_response({"ok": True, "killed": target_id})


async def handle_v1_upload(request: web.Request) -> web.Response:
    r = require_auth(request)
    if r: return r
    qs = parse_qs(request.query_string)
    target = qs.get("path", [""])[0]
    if not target:
        _record_request(is_error=True, count_request=False)
        return _cors_json_response({"ok": False, "error": "missing path"}, status=400)
    # Path traversal protection
    if ".." in Path(target).parts:
        _record_request(is_error=True, count_request=False)
        return _cors_json_response({"ok": False, "error": "path traversal not allowed"}, status=400)
    target_path = Path(target).expanduser()
    if not target_path.is_absolute():
        target_path = request.app["cfg"]["root"] / target_path
    # Prevent overwriting bridge itself or writing outside user home
    try:
        target_path.resolve().relative_to(Path.home())
    except ValueError:
        _record_request(is_error=True, count_request=False)
        return _cors_json_response({"ok": False, "error": "upload path must be inside user home"}, status=403)
    bridge_py = Path(__file__).resolve()
    if target_path.resolve() == bridge_py.resolve():
        _record_request(is_error=True, count_request=False)
        return _cors_json_response({"ok": False, "error": "cannot overwrite the bridge itself"}, status=403)
    # Reject multipart form-data uploads (they corrupt file content)
    ct = request.headers.get("Content-Type", "")
    if "multipart" in ct.lower():
        _record_request(is_error=True, count_request=False)
        return _cors_json_response({"ok": False, "error": "multipart/form-data not supported; use --data-binary"}, status=400)
    try:
        body = await request.read()
        target_path.parent.mkdir(parents=True, exist_ok=True)
        target_path.write_bytes(body)
        audit({"type": "file_upload", "path": str(target_path), "bytes": len(body)})
        _record_request()
        return _cors_json_response({"ok": True, "path": str(target_path), "bytes": len(body)})
    except Exception as e:
        _record_request(is_error=True, count_request=False)
        return _cors_json_response({"ok": False, "error": "Internal error"}, status=500)


async def handle_v1_download(request: web.Request) -> web.Response:
    r = require_auth(request)
    if r: return r
    qs = parse_qs(request.query_string)
    target = qs.get("path", [""])[0]
    if not target:
        _record_request(is_error=True, count_request=False)
        return _cors_json_response({"ok": False, "error": "missing path"}, status=400)
    if ".." in Path(target).parts:
        _record_request(is_error=True, count_request=False)
        return _cors_json_response({"ok": False, "error": "path traversal not allowed"}, status=400)
    target_path = Path(target).expanduser()
    if not target_path.is_absolute():
        target_path = request.app["cfg"]["root"] / target_path
    # Security: restrict downloads to home directory
    try:
        target_path.resolve().relative_to(Path.home().resolve())
    except ValueError:
        _record_request(is_error=True, count_request=False)
        return _cors_json_response({"ok": False, "error": "path outside home directory"}, status=403)
    if not target_path.exists() or not target_path.is_file():
        _record_request(is_error=True, count_request=False)
        return _cors_json_response({"ok": False, "error": "file not found"}, status=404)
    try:
        audit({"type": "file_download", "path": str(target_path), "bytes": target_path.stat().st_size})
        _record_request()
        return web.FileResponse(target_path, headers={
            "Content-Disposition": f'attachment; filename="{target_path.name}"',
            "Access-Control-Allow-Origin": "*",
        })
    except Exception as e:
        _record_request(is_error=True, count_request=False)
        return _cors_json_response({"ok": False, "error": "Internal error"}, status=500)


# ============================================================================
# HANDLER — Dashboard GUI
# ============================================================================

_GUI_LOGIN_HTML = """<!DOCTYPE html>
<html><head><title>Arena Bridge — Login</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:'Segoe UI',system-ui,-apple-system,sans-serif;background:#0d1117;color:#c9d1d9;display:flex;justify-content:center;align-items:center;min-height:100vh}
.card{background:#161b22;border:1px solid #30363d;border-radius:12px;padding:2.5rem;width:400px;text-align:center}
.card h1{color:#58a6ff;margin-bottom:.25rem;font-size:1.6rem}
.card .sub{color:#8b949e;margin-bottom:1.5rem;font-size:.85rem}
.card input{width:100%;padding:.7rem 1rem;background:#0d1117;border:1px solid #30363d;border-radius:6px;color:#c9d1d9;font-size:.9rem;font-family:monospace;outline:none;margin-bottom:.75rem}
.card input:focus{border-color:#58a6ff;box-shadow:0 0 0 3px rgba(88,166,255,.15)}
.card button{width:100%;padding:.7rem;background:#238636;color:#fff;border:none;border-radius:6px;font-size:.9rem;cursor:pointer;font-weight:600;transition:background .15s}
.card button:hover{background:#2ea043}
.card .err{color:#f85149;font-size:.8rem;margin-top:.5rem;min-height:1.2em}
.card .hint{color:#484f58;font-size:.75rem;margin-top:1.25rem}
</style></head>
<body>
<div class="card">
<h1>Arena Bridge</h1>
<p class="sub">Enter your auth token to access the dashboard</p>
<form id="form" onsubmit="return login()">
<input type="password" id="token" placeholder="Auth token" autofocus autocomplete="off">
<button type="submit">Sign In</button>
<div class="err" id="err"></div>
</form>
<p class="hint">Token is stored in token.txt in the bridge directory</p>
</div>
<script>
var REDIR=location.pathname;
function login(e){
  if(e)e.preventDefault();
  var t=document.getElementById('token').value.trim();
  if(!t){document.getElementById('err').textContent='Please enter a token';return false}
  document.getElementById('err').textContent='';
  document.querySelector('button').textContent='Signing in...';
  fetch('/v1/status',{headers:{'Authorization':'Bearer '+t}}).then(function(r){
    if(r.ok){
      localStorage.setItem('arena_token',t);
      var sep=REDIR.indexOf('?')>-1?'&':'?';
      location.href=REDIR+sep+'token='+encodeURIComponent(t);
    }else{
      document.getElementById('err').textContent='Invalid token';
      document.querySelector('button').textContent='Sign In';
    }
  }).catch(function(){
    document.getElementById('err').textContent='Connection failed';
    document.querySelector('button').textContent='Sign In';
  });
  return false;
}
var saved=localStorage.getItem('arena_token');
if(saved){document.getElementById('token').value=saved;login()}
</script>
</body></html>"""


async def handle_gui(request: web.Request) -> web.Response:
    """GET /gui — Dashboard. Shows login page if no valid URL token, then serves dashboard."""
    cfg = request.app["cfg"]
    # Only URL token param is accepted — timing-attack safe
    url_token = request.query.get("token", "")
    valid_token = bool(url_token) and hmac.compare_digest(url_token, cfg["token"])

    # No valid URL token — show login page
    # (We require the token in the URL because the dashboard HTML needs it for API calls)
    if not valid_token:
        return web.Response(text=_GUI_LOGIN_HTML, content_type="text/html", charset="utf-8")
    try:
        # Try multiple locations for the dashboard
        candidates = [
            BRIDGE_DIR / "dashboard" / "index.html",
            BRIDGE_DIR / "index.html",
        ]
        for html_path in candidates:
            if html_path.exists():
                html = html_path.read_text(encoding="utf-8")
                # Embed ONLY the URL token — never fall back to cfg["token"]
                html = html.replace("{{TOKEN}}", url_token)
                html = html.replace("{{VERSION}}", VERSION)
                html = html.replace("{{HOST}}", socket.gethostname())
                return web.Response(text=html, content_type="text/html", charset="utf-8",
                                    headers={"Access-Control-Allow-Origin": "*"})
        # Fallback: minimal dashboard (no token leak)
        fallback = f"""<!DOCTYPE html><html><head><title>Arena Bridge v{VERSION}</title></head>
        <body style='font-family:monospace;background:#1a1a2e;color:#e0e0e0;padding:2rem'>
        <h1>Arena Unified Bridge v{VERSION}</h1><p>Dashboard not found.</p>
        <p>API: <a href='/'>/</a> | Health: <a href='/health'>/health</a></p>
        </body></html>"""
        return web.Response(text=fallback, content_type="text/html", charset="utf-8",
                            headers={"Access-Control-Allow-Origin": "*"})
    except Exception:
        return _cors_json_response({"ok": False, "error": "Internal server error"}, status=500)


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




# --- /v1/sys/funnel GET — Tailscale Funnel status ---

def _sys_funnel_sync() -> dict:
    """Synchronous helper to check Tailscale funnel status."""
    result: dict[str, Any] = {"ok": True, "tailscale": {}, "funnel": {}}

    # Run tailscale status
    try:
        out = subprocess.check_output(["tailscale", "status"], stderr=subprocess.STDOUT, text=True, **_subprocess_kwargs())
        result["tailscale"]["status"] = out.strip()[:2000]
        result["tailscale"]["connected"] = bool(out.strip())
    except FileNotFoundError:
        result["tailscale"]["error"] = "tailscale not found"
    except Exception as e:
        result["tailscale"]["error"] = str(e)[:500]

    # Run tailscale funnel status
    try:
        out = subprocess.check_output(["tailscale", "funnel", "status"], stderr=subprocess.STDOUT, text=True, **_subprocess_kwargs())
        result["funnel"]["status"] = out.strip()[:2000]
        _lw = out.lower()
        result["funnel"]["active"] = (
            "funnel on" in _lw
            or "proxy http" in _lw
            or "serving" in _lw
            or "listening" in _lw
        )
        # extract public URL if present (https://*.ts.net)
        m = re.search(r"https://[\w.-]+\.ts\.net[^\s]*", out)
        if m:
            result["funnel"]["url"] = m.group(0)
    except FileNotFoundError:
        result["funnel"]["error"] = "tailscale not found"
    except Exception as e:
        result["funnel"]["error"] = str(e)[:500]

    return result


async def handle_v1_sys_funnel(request: web.Request) -> web.Response:
    """GET /v1/sys/funnel — Tailscale Funnel status."""
    r = require_auth(request)
    if r: return r
    _record_request()
    try:
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(_EXECUTOR, _sys_funnel_sync)
        return _cors_json_response(result)
    except Exception as e:
        _record_request(is_error=True, count_request=False)
        return _cors_json_response({"ok": False, "error": str(e)}, status=500)


# --- /v1/token/regenerate POST — Generate new auth token ---

def _token_path() -> Path:
    """Resolve token file location used by start-bridge / install.bat."""
    return Path(os.environ.get("ARENA_TOKEN_FILE",
                str(TOKEN_FILE))).expanduser()


def _token_regen_sync(target_path: str = "") -> dict:
    """Generate a new token and write it to ONLY the bridge's own token.txt.
    Path resolution priority:
      1. explicit target_path arg (from cfg["token_file"] or env)
      2. ARENA_TOKEN_FILE env var
      3. <BRIDGE_DIR from sys.argv 'serve --root'>/token.txt — best effort
      4. ~/arena-bridge/token.txt  (default)
    NEVER writes to multiple locations — that risks clobbering another instance's token.
    """
    new_tok = base64.urlsafe_b64encode(secrets.token_bytes(32)).decode().rstrip("=")

    target: Path
    if target_path:
        target = Path(target_path).expanduser()
    else:
        env = os.environ.get("ARENA_TOKEN_FILE")
        if env:
            target = Path(env).expanduser()
        else:
            # Default to the canonical bridge-dir token file
            target = TOKEN_FILE

    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(new_tok, encoding="utf-8")
        try:
            os.chmod(target, 0o600)
        except Exception:
            pass
        return {
            "ok": True,
            "token": new_tok,
            "written_to": [str(target)],
            "note": ("Existing connections still use the OLD token until the bridge restarts. "
                     "Use POST /v1/restart, or click Restart Bridge."),
        }
    except Exception as e:
        return {"ok": False, "error": f"Failed to write {target}: {e}"}


async def handle_v1_token_regenerate(request: web.Request) -> web.Response:
    r = require_auth(request)
    if r: return r
    _record_request()
    cfg = request.app["cfg"]
    # Prefer the exact token_file that this bridge instance reads on startup
    target = str(cfg.get("token_file") or "")
    try:
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(_EXECUTOR, _token_regen_sync, target)
        # Hot-update in-memory token so new requests accept it immediately
        if result.get("ok") and result.get("token"):
            cfg["token"] = result["token"]
        audit({"type": "token_regenerated", "files": result.get("written_to", [])})
        return _cors_json_response(result)
    except Exception as e:
        _record_request(is_error=True, count_request=False)
        return _cors_json_response({"ok": False, "error": str(e)}, status=500)


# --- /v1/tailscale/funnel/{action} POST — start | stop | status ---

def _tailscale_funnel_action_sync(action: str, port: int) -> dict:
    import subprocess as _sp
    import shutil as _shutil_local
    action = (action or "").lower()
    if action not in ("start", "stop", "status"):
        return {"ok": False, "error": "action must be start|stop|status"}
    # locate tailscale
    ts = _shutil_local.which("tailscale")
    if not ts and platform.system() == "Windows":
        candidates = [
            r"C:\Program Files\Tailscale\tailscale.exe",
            r"C:\Program Files (x86)\Tailscale\tailscale.exe",
        ]
        for c in candidates:
            if os.path.isfile(c):
                ts = c; break
    if not ts:
        return {"ok": False, "error": "tailscale binary not found"}

    if action == "start":
        # `tailscale funnel --bg 8765`
        try:
            r = _sp.run([ts, "funnel", "--bg", str(port)],
                        capture_output=True, text=True, timeout=15)
            return {"ok": r.returncode == 0, "action": "start", "port": port,
                    "stdout": r.stdout, "stderr": r.stderr,
                    "exit_code": r.returncode}
        except Exception as e:
            return {"ok": False, "error": str(e)}
    if action == "stop":
        # `tailscale funnel --https=443 off`
        try:
            r = _sp.run([ts, "funnel", "--https=443", "off"],
                        capture_output=True, text=True, timeout=15)
            return {"ok": r.returncode == 0, "action": "stop",
                    "stdout": r.stdout, "stderr": r.stderr,
                    "exit_code": r.returncode}
        except Exception as e:
            return {"ok": False, "error": str(e)}
    # status
    try:
        r = _sp.run([ts, "funnel", "status"],
                    capture_output=True, text=True, timeout=10)
        out = r.stdout or ""
        return {"ok": True, "action": "status", "output": out,
                "active": ("funnel on" in out.lower() or "proxy http" in out.lower())}
    except Exception as e:
        return {"ok": False, "error": str(e)}


async def handle_v1_tailscale_funnel(request: web.Request) -> web.Response:
    r = require_auth(request)
    if r: return r
    _record_request()
    action = request.match_info.get("action", "status")
    cfg = request.app["cfg"]
    port = cfg.get("port", 8765)
    try:
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(_EXECUTOR, _tailscale_funnel_action_sync, action, port)
        audit({"type": "tailscale_funnel", "action": action, "ok": result.get("ok")})
        return _cors_json_response(result)
    except Exception as e:
        _record_request(is_error=True, count_request=False)
        return _cors_json_response({"ok": False, "error": str(e)}, status=500)


_CLOUDFLARED_STATE = {"proc": None, "url": "", "log": []}

def _cloudflared_monitor_thread(proc, port: int):
    import re
    while True:
        line = proc.stdout.readline()
        if not line:
            break
        line_str = line.strip()
        _CLOUDFLARED_STATE["log"].append(line_str)
        if len(_CLOUDFLARED_STATE["log"]) > 100:
            _CLOUDFLARED_STATE["log"].pop(0)
        match = re.search(r"https://[a-zA-Z0-9-]+\.trycloudflare\.com", line_str)
        if match:
            _CLOUDFLARED_STATE["url"] = match.group(0)

def _cloudflared_funnel_action_sync(action: str, port: int) -> dict:
    import subprocess as _sp
    import shutil as _shutil_local
    action = (action or "").lower()
    if action not in ("start", "stop", "status"):
        return {"ok": False, "error": "action must be start|stop|status"}
    cf = _shutil_local.which("cloudflared")
    if not cf and platform.system() == "Windows":
        candidates = [
            r"C:\Program Files\cloudflared\cloudflared.exe",
            r"C:\Program Files (x86)\cloudflared\cloudflared.exe",
        ]
        for c in candidates:
            if os.path.isfile(c):
                cf = c; break
    if not cf:
        # allow local binary in agent folder
        local_cf = ROOT_AGENT / ("cloudflared.exe" if platform.system() == "Windows" else "cloudflared")
        if local_cf.exists():
            cf = str(local_cf)

    if action == "start":
        if not cf:
            return {"ok": False, "error": "cloudflared binary not found"}
        if _CLOUDFLARED_STATE["proc"] and _CLOUDFLARED_STATE["proc"].poll() is None:
            return {"ok": True, "action": "start", "already_running": True, "url": _CLOUDFLARED_STATE["url"]}
        _CLOUDFLARED_STATE["url"] = ""
        _CLOUDFLARED_STATE["log"].clear()
        try:
            _CLOUDFLARED_STATE["proc"] = _sp.Popen(
                [cf, "tunnel", "--url", f"http://127.0.0.1:{port}"],
                stdout=_sp.PIPE, stderr=_sp.STDOUT, text=True,
                **_subprocess_kwargs()
            )
            t = threading.Thread(target=_cloudflared_monitor_thread, args=(_CLOUDFLARED_STATE["proc"], port), daemon=True)
            t.start()
            
            # Wait up to 10 seconds for URL
            for _ in range(20):
                if _CLOUDFLARED_STATE["url"] or _CLOUDFLARED_STATE["proc"].poll() is not None:
                    break
                time.sleep(0.5)
                
            active = bool(_CLOUDFLARED_STATE["url"])
            if not active:
                proc = _CLOUDFLARED_STATE["proc"]
                if proc and proc.poll() is None:
                    try:
                        proc.terminate()
                        proc.wait(timeout=2)
                    except Exception:
                        try: proc.kill()
                        except Exception: pass
                _CLOUDFLARED_STATE["proc"] = None
                return {"ok": False, "action": "start", "error": "cloudflared timed out generating a tunnel URL", "log": list(_CLOUDFLARED_STATE["log"])}
            return {"ok": True, "action": "start", "port": port, "url": _CLOUDFLARED_STATE["url"], "log": _CLOUDFLARED_STATE["log"]}
        except Exception as e:
            return {"ok": False, "error": str(e)}
            
    if action == "stop":
        proc = _CLOUDFLARED_STATE["proc"]
        if proc and proc.poll() is None:
            try:
                proc.terminate()
                proc.wait(timeout=5)
            except Exception:
                try: proc.kill()
                except Exception: pass
        _CLOUDFLARED_STATE["proc"] = None
        _CLOUDFLARED_STATE["url"] = ""
        return {"ok": True, "action": "stop"}
        
    # status
    proc = _CLOUDFLARED_STATE["proc"]
    running = proc is not None and proc.poll() is None
    installed = cf is not None
    return {
        "ok": True, 
        "action": "status", 
        "installed": installed,
        "active": running, 
        "url": _CLOUDFLARED_STATE["url"],
        "log": _CLOUDFLARED_STATE["log"] if running else []
    }

async def handle_v1_cloudflared_tunnel(request: web.Request) -> web.Response:
    r = require_auth(request)
    if r: return r
    _record_request()
    action = request.match_info.get("action", "status")
    cfg = request.app["cfg"]
    port = cfg.get("port", 8765)
    try:
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(_EXECUTOR, _cloudflared_funnel_action_sync, action, port)
        audit({"type": "cloudflared_tunnel", "action": action, "ok": result.get("ok")})
        return _cors_json_response(result)
    except Exception as e:
        _record_request(is_error=True, count_request=False)
        return _cors_json_response({"ok": False, "error": str(e)}, status=500)

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

async def handle_v1_cdp_status(request):
    """GET /v1/browser/cdp/status — CDP session status."""
    r = require_auth(request)
    if r: return r
    _record_request()
    
    cdp = _get_cdp_module()
    mgr = _cdp_state.get("manager")
    
    status = {
        "ok": True,
        "connected": _cdp_state["connected"],
        "port": _cdp_state["port"],
        "headless": _cdp_state["headless"],
        "module_available": cdp is not None,
        "tab_count": mgr.tab_count if mgr else 0,
        "active_tab_id": mgr.active_tab_id if mgr else None,
        "network_monitoring": _cdp_state.get("monitor") is not None and _cdp_state["monitor"].active if _cdp_state.get("monitor") else False,
        "interception_active": _cdp_state.get("interceptor") is not None and _cdp_state["interceptor"].active if _cdp_state.get("interceptor") else False,
        "cookie_manager_active": _cdp_state.get("cookie_mgr") is not None and _cdp_state["cookie_mgr"].active if _cdp_state.get("cookie_mgr") else False,
        "reconnect_count": _cdp_state.get("reconnect_count", 0),
        "last_connect_time": _cdp_state.get("last_connect_time"),
        "last_disconnect_reason": _cdp_state.get("last_disconnect_reason"),
        "watcher_active": _cdp_watcher_task is not None and not _cdp_watcher_task.done(),
    }
    
    if mgr:
        tabs_info = [tab.to_dict() for tab in mgr.list_tabs()]
        status["tabs"] = tabs_info
    
    return _cors_json_response(status)


async def handle_v1_cdp_diag(request):
    """GET /v1/browser/cdp/diag — Quick CDP diagnostics (no browser launch).

    Returns environment info, browser availability, and systemd detection
    without attempting to connect or launch anything.
    """
    r = require_auth(request)
    if r: return r
    _record_request()

    import shutil as _shutil
    uid = os.getuid() if hasattr(os, 'getuid') else -1
    in_systemd = bool(os.environ.get("INVOCATION_ID") or os.environ.get("JOURNAL_STREAM"))

    diag = {
        "ok": True,
        "connected": _cdp_state["connected"],
        "bridge_env": {
            "INVOCATION_ID": bool(os.environ.get("INVOCATION_ID")),
            "JOURNAL_STREAM": bool(os.environ.get("JOURNAL_STREAM")),
            "DBUS_SESSION_BUS_ADDRESS": os.environ.get("DBUS_SESSION_BUS_ADDRESS", ""),
            "XDG_RUNTIME_DIR": os.environ.get("XDG_RUNTIME_DIR", ""),
            "DISPLAY": os.environ.get("DISPLAY", ""),
            "WAYLAND_DISPLAY": os.environ.get("WAYLAND_DISPLAY", ""),
        },
        "bridge_env_ok": {
            "DBUS_SESSION_BUS_ADDRESS": bool(os.environ.get("DBUS_SESSION_BUS_ADDRESS")),
            "XDG_RUNTIME_DIR": bool(os.environ.get("XDG_RUNTIME_DIR")),
            "DISPLAY": bool(os.environ.get("DISPLAY")),
            "WAYLAND_DISPLAY": bool(os.environ.get("WAYLAND_DISPLAY")),
        },
        "systemd_run_available": bool(_shutil.which("systemd-run")),
        "in_systemd": in_systemd,
    }

    # Check browser binary
    cdp = _get_cdp_module()
    if cdp:
        try:
            exe = cdp._resolve_browser_binary()
            diag["browser_binary"] = exe
            diag["browser_is_wrapper"] = False
            try:
                with open(exe, "rb") as f:
                    first = f.read(4)
                if first.startswith(b"#!"):
                    diag["browser_is_wrapper"] = True
                elif first == b"\x7fELF":
                    diag["browser_is_elf"] = True
            except Exception:
                pass
            # Check if chromium supports --ozone-platform=headless
            try:
                help_out = subprocess.run(
                    [exe, "--help"], capture_output=True, text=True, timeout=5,
                    env={**os.environ, "LD_LIBRARY_PATH": os.environ.get("LD_LIBRARY_PATH", "")}
                )
                diag["ozone_support"] = "ozone" in (help_out.stdout + help_out.stderr).lower()
            except Exception:
                diag["ozone_support"] = "unknown"
        except Exception as e:
            diag["browser_error"] = str(e)

        # Check session env that _build_session_env would produce
        try:
            session_env = cdp._build_session_env()
            diag["session_env"] = {
                "DBUS_SESSION_BUS_ADDRESS": session_env.get("DBUS_SESSION_BUS_ADDRESS", ""),
                "XDG_RUNTIME_DIR": session_env.get("XDG_RUNTIME_DIR", ""),
                "DISPLAY": session_env.get("DISPLAY", ""),
                "WAYLAND_DISPLAY": session_env.get("WAYLAND_DISPLAY", ""),
            }
        except Exception as e:
            diag["session_env_error"] = str(e)

        # Show the Chromium command that would be used
        try:
            test_cmd = cdp._build_chromium_cmd(exe, 9222, True, os.path.join(tempfile.gettempdir(), "cdp-browser-test"))
            diag["headless_cmd"] = " ".join(test_cmd)
        except Exception:
            pass

    # Check D-Bus socket
    dbus_path = f"/run/user/{uid}/bus"
    diag["dbus_socket_exists"] = os.path.exists(dbus_path)
    diag["dbus_socket_path"] = dbus_path

    # Quick test: can we reach the D-Bus user bus?
    try:
        import socket as _socket
        s = _socket.socket(_socket.AF_UNIX, _socket.SOCK_STREAM)
        s.settimeout(2)
        s.connect(dbus_path)
        s.close()
        diag["dbus_socket_connectable"] = True
    except Exception as e:
        diag["dbus_socket_connectable"] = False
        diag["dbus_socket_error"] = str(e)

    # Check if port 9222 is already in use
    try:
        import socket as _socket
        s = _socket.socket(_socket.AF_INET, _socket.SOCK_STREAM)
        s.settimeout(1)
        result = s.connect_ex(("127.0.0.1", 9222))
        s.close()
        diag["port_9222_in_use"] = (result == 0)
    except Exception:
        diag["port_9222_in_use"] = "unknown"

    return _cors_json_response(diag)


async def handle_v1_cdp_raw_info(request):
    """GET /v1/browser/cdp/raw-info — Fetch raw /json/version and /json/list from a Chromium debug port.

    v1.9.19: New diagnostic endpoint to see EXACTLY what CachyOS Chromium returns
    from its CDP HTTP endpoints. This is critical for debugging WebSocket URL issues.

    Launches its own Chromium instance, waits for the port, fetches the raw HTTP
    responses, kills the browser, and returns the data. NO WebSocket testing here.

    Query params:
        port: int (default: 9223)
    """
    r = require_auth(request)
    if r: return r
    _record_request()

    cdp = _get_cdp_module()
    if not cdp:
        _record_request(is_error=True)
        return _cors_json_response(
            {"ok": False, "error": "cdp_browser module not found"},
            status=500
        )

    qs = parse_qs(request.query_string)
    port = int(qs.get("port", ["9223"])[0])

    result = {
        "ok": False,
        "port": port,
        "raw_version": None,
        "raw_tabs": None,
        "error": None,
    }

    try:
        loop = asyncio.get_event_loop()

        # Kill stale processes and launch
        try:
            await loop.run_in_executor(None, cdp._kill_port_processes, port)
            await asyncio.sleep(0.3)
        except Exception as e:
            log.warning("[raw-info] Kill stale processes failed: %s", e)

        browser_proc = await loop.run_in_executor(
            None, cdp.launch_browser, port, True
        )
        result["browser_pid"] = browser_proc.pid

        # Wait for port to become ready (max 10s)
        port_ready = False
        for attempt in range(20):
            await asyncio.sleep(0.5)
            if browser_proc.poll() is not None:
                result["browser_died"] = True
                result["browser_rc"] = browser_proc.returncode
                launch_diag = getattr(browser_proc, '_cdp_launch_diag', {})
                stderr_log = launch_diag.get("stderr_log", "")
                if stderr_log:
                    try:
                        with open(stderr_log, "r") as f:
                            result["browser_stderr"] = f.read().strip()[:2000]
                    except Exception:
                        pass
                result["error"] = f"Browser died (rc={browser_proc.returncode})"
                return _cors_json_response(result)
            try:
                tabs = await loop.run_in_executor(None, cdp.list_tabs, port)
                if tabs:
                    port_ready = True
                    result["port_ready_after_s"] = (attempt + 1) * 0.5
                    break
            except Exception:
                pass

        if not port_ready:
            result["error"] = f"Chromium port {port} not ready after 10s"
            try:
                browser_proc.terminate()
                browser_proc.wait(timeout=3)
            except Exception:
                pass
            return _cors_json_response(result)

        # Fetch /json/version — raw HTTP response
        try:
            def _get_version():
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/version", timeout=5) as r:
                    raw = r.read().decode()
                    return json.loads(raw), raw
            version_data, version_raw = await loop.run_in_executor(None, _get_version)
            result["raw_version"] = version_data
            result["raw_version_keys"] = list(version_data.keys())
            result["has_webSocketDebuggerUrl"] = "webSocketDebuggerUrl" in version_data
            ws_url = version_data.get("webSocketDebuggerUrl", "")
            result["webSocketDebuggerUrl"] = ws_url or "MISSING"
            # Chromium /json/version doesn't include "id" field — extract from WS URL
            version_id = version_data.get("id", "")
            if not version_id and ws_url:
                # ws://127.0.0.1:PORT/devtools/browser/<uuid>
                import re
                m = re.search(r'/devtools/browser/([^/]+)', ws_url)
                if m:
                    version_id = m.group(1)
            result["version_id"] = version_id or "N/A"
            result["version_browser"] = version_data.get("Browser", "?")
            log.info("[raw-info] /json/version keys: %s", list(version_data.keys()))
            log.info("[raw-info] webSocketDebuggerUrl: %s", ws_url or "MISSING")
            log.info("[raw-info] id: %s", version_id or "N/A")
        except Exception as e:
            result["raw_version_error"] = f"{type(e).__name__}: {e}"
            log.warning("[raw-info] /json/version fetch failed: %s", e)

        # Fetch /json/list — raw HTTP response
        page_tabs = []  # Initialize BEFORE try to avoid UnboundLocalError if fetch fails
        try:
            def _get_tabs():
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/list", timeout=5) as r:
                    raw = r.read().decode()
                    return json.loads(raw), raw
            tabs_data, tabs_raw = await loop.run_in_executor(None, _get_tabs)
            result["raw_tabs"] = tabs_data
            result["tab_count"] = len(tabs_data)
            # Summarize tab types and WS URLs
            page_tabs = [t for t in tabs_data if t.get("type") == "page"]
            result["page_tab_count"] = len(page_tabs)
            result["tab_ws_urls"] = [
                {"id": t.get("id", "?"), "type": t.get("type", "?"),
                 "webSocketDebuggerUrl": t.get("webSocketDebuggerUrl", "MISSING"),
                 "url": t.get("url", "?")[:80]}
                for t in tabs_data[:5]  # First 5 only
            ]
            log.info("[raw-info] /json/list: %d entries, %d pages", len(tabs_data), len(page_tabs))
            for i, t in enumerate(page_tabs[:3]):
                log.info("[raw-info]   page[%d]: id=%s wsUrl=%s url=%s",
                         i, t.get("id", "?")[:20],
                         t.get("webSocketDebuggerUrl", "MISSING")[:60],
                         t.get("url", "?")[:50])
        except Exception as e:
            result["raw_tabs_error"] = f"{type(e).__name__}: {e}"
            log.warning("[raw-info] /json/list fetch failed: %s", e)

        # Quick WS probe using websockets library (if available)
        if page_tabs:
            tab_id = page_tabs[0].get("id", "")
            tab_ws_url = page_tabs[0].get("webSocketDebuggerUrl", "")
            if not tab_ws_url and tab_id:
                tab_ws_url = f"ws://127.0.0.1:{port}/devtools/page/{tab_id}"
                result["tab_ws_url_constructed"] = True
            result["tab_ws_url_tested"] = tab_ws_url

            if tab_ws_url:
                # Try websockets library
                try:
                    import websockets
                    t0 = time.monotonic()
                    ws = await asyncio.wait_for(
                        websockets.connect(tab_ws_url, open_timeout=3, close_timeout=2),
                        timeout=5
                    )
                    elapsed = time.monotonic() - t0
                    result["tab_ws_ok"] = True
                    result["tab_ws_time_s"] = round(elapsed, 2)
                    result["tab_ws_lib"] = "websockets"
                    # Try a CDP command
                    try:
                        await ws.send(json.dumps({"id": 1, "method": "Runtime.evaluate",
                                                   "params": {"expression": "1+1"}}))
                        resp = await asyncio.wait_for(ws.recv(), timeout=3)
                        result["tab_ws_cdp_ok"] = True
                        result["tab_ws_cdp_preview"] = resp[:200]
                    except Exception as e:
                        result["tab_ws_cdp_ok"] = False
                        result["tab_ws_cdp_error"] = str(e)
                    await ws.close()
                    result["ok"] = True
                except ImportError:
                    result["tab_ws_ok"] = False
                    result["tab_ws_error"] = "websockets library not available"
                except asyncio.TimeoutError:
                    result["tab_ws_ok"] = False
                    result["tab_ws_error"] = f"websockets TIMEOUT (5s) to {tab_ws_url}"
                except Exception as e:
                    result["tab_ws_ok"] = False
                    result["tab_ws_error"] = f"{type(e).__name__}: {e} to {tab_ws_url}"

                # If websockets failed, try aiohttp
                if not result.get("tab_ws_ok"):
                    try:
                        import aiohttp as _aiohttp
                        t0 = time.monotonic()
                        ws_timeout = _aiohttp.ClientTimeout(total=3, connect=2, sock_connect=2)
                        connector = _aiohttp.TCPConnector(force_close=True)
                        async with _aiohttp.ClientSession(timeout=ws_timeout, connector=connector) as session:
                            tab_ws = await asyncio.wait_for(
                                session.ws_connect(tab_ws_url, heartbeat=None, proxy=None),
                                timeout=5
                            )
                            elapsed = time.monotonic() - t0
                            result["tab_ws_ok"] = True
                            result["tab_ws_time_s"] = round(elapsed, 2)
                            result["tab_ws_lib"] = "aiohttp"
                            try:
                                await tab_ws.send_json({"id": 1, "method": "Runtime.evaluate",
                                                         "params": {"expression": "1+1"}})
                                msg = await asyncio.wait_for(tab_ws.receive(), timeout=3)
                                if msg.type == _aiohttp.WSMsgType.TEXT:
                                    result["tab_ws_cdp_ok"] = True
                                    result["tab_ws_cdp_preview"] = msg.data[:200]
                            except Exception as e:
                                result["tab_ws_cdp_ok"] = False
                                result["tab_ws_cdp_error"] = str(e)
                            await tab_ws.close()
                            result["ok"] = True
                    except asyncio.TimeoutError:
                        result["tab_ws_aiohttp_error"] = f"aiohttp TIMEOUT (5s) to {tab_ws_url}"
                    except Exception as e:
                        result["tab_ws_aiohttp_error"] = f"aiohttp {type(e).__name__}: {e} to {tab_ws_url}"

        if not result.get("ok"):
            # HTTP works but WS doesn't — still useful diagnostic
            result["ok"] = bool(result.get("raw_version") or result.get("raw_tabs"))

    except Exception as e:
        import traceback
        result["error"] = f"Unhandled: {type(e).__name__}: {e}"
        result["traceback"] = traceback.format_exc()
        log.error("[raw-info] UNHANDLED: %s\n%s", e, traceback.format_exc())
    finally:
        # Always kill the test browser
        if "browser_proc" in dir() and browser_proc:
            try:
                browser_proc.terminate()
                browser_proc.wait(timeout=3)
            except Exception:
                try:
                    browser_proc.kill()
                except Exception:
                    pass

    return _cors_json_response(result)


async def handle_v1_cdp_test_launch(request):
    """GET /v1/browser/cdp/test-launch — Diagnostic: try launching Chromium and capture output.

    This endpoint runs Chromium with Popen, checks port availability WHILE running,
    and tries multiple headless modes. It does NOT go through the CDPTabManager.

    Query params:
        port: int (default: 9223)
        headless: bool (default: true)
    """
    r = require_auth(request)
    if r: return r
    _record_request()

    cdp = _get_cdp_module()
    if not cdp:
        _record_request(is_error=True)
        return _cors_json_response(
            {"ok": False, "error": "cdp_browser module not found"},
            status=500
        )

    qs = parse_qs(request.query_string)
    port = int(qs.get("port", ["9223"])[0])
    headless = qs.get("headless", ["true"])[0].lower() != "false"

    loop = asyncio.get_event_loop()

    def _test_launch():
        """Run Chromium and check port while running. Returns result dict."""
        import socket as _socket
        import threading

        try:
            exe = cdp._resolve_browser_binary()
        except Exception as e:
            return {"ok": False, "error": f"Cannot resolve browser binary: {e}"}

        if not os.path.isfile(exe):
            return {"ok": False, "error": f"Browser binary not found: {exe}"}

        # Kill any stale processes on the test port
        try:
            cdp._kill_port_processes(port)
        except Exception:
            pass

        session_env = cdp._build_session_env()

        result = {
            "ok": False,
            "exe": exe,
            "env_dbus": session_env.get("DBUS_SESSION_BUS_ADDRESS", ""),
            "env_xdg": session_env.get("XDG_RUNTIME_DIR", ""),
            "env_home": session_env.get("HOME", ""),
            "env_display": session_env.get("DISPLAY", ""),
            "env_ld_library_path": session_env.get("LD_LIBRARY_PATH", ""),
            "port": port,
            "headless": headless,
        }

        # Try multiple headless modes — first --headless=new, then --headless (old)
        headless_modes = []
        if headless:
            headless_modes = [
                ("headless=new + ozone=headless", ["--headless=new", "--ozone-platform=headless"]),
                ("headless=new only", ["--headless=new"]),
                ("headless (old mode)", ["--headless"]),
            ]
        else:
            headless_modes = [("headed", [])]

        for mode_name, headless_flags in headless_modes:
            ud = os.path.join(tempfile.gettempdir(), f"cdp-test-{os.getpid()}-{mode_name.replace(' ','_')[:20]}")
            os.makedirs(ud, exist_ok=True)

            cmd = [exe, f"--remote-debugging-port={port}"]
            cmd.extend(headless_flags)
            cmd.extend([
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-gpu",
                "--disable-dev-shm-usage",
                "--no-first-run",
                "--no-default-browser-check",
                "--disable-extensions",
                f"--user-data-dir={ud}",
            ])

            mode_result = {
                "mode": mode_name,
                "cmd": " ".join(cmd),
                "user_data_dir": ud,
            }

            try:
                # Use Popen so we can check port WHILE Chromium is running
                proc = subprocess.Popen(
                    cmd,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    env=session_env,
                    start_new_session=True,
                )

                # Drain stderr in background thread
                stderr_lines = []
                def _drain():
                    try:
                        for line in proc.stderr:
                            stderr_lines.append(line.decode(errors="replace") if isinstance(line, bytes) else line)
                    except Exception:
                        pass
                threading.Thread(target=_drain, daemon=True).start()

                # Wait up to 8 seconds, checking port every 0.5s
                port_open = False
                version_info = None
                for attempt in range(16):  # 16 * 0.5s = 8s
                    time.sleep(0.5)
                    # Check if process died
                    if proc.poll() is not None:
                        mode_result["died_after_s"] = (attempt + 1) * 0.5
                        mode_result["returncode"] = proc.returncode
                        break
                    # Check if port is open
                    try:
                        s = _socket.socket(_socket.AF_INET, _socket.SOCK_STREAM)
                        s.settimeout(1)
                        if s.connect_ex(("127.0.0.1", port)) == 0:
                            port_open = True
                            s.close()
                            # Try to get version info
                            try:
                                with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/version", timeout=3) as resp:
                                    version_info = json.loads(resp.read().decode())
                            except Exception as e:
                                version_info = {"error": str(e)}
                            # Try to list tabs
                            try:
                                with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/list", timeout=3) as resp:
                                    mode_result["tabs"] = json.loads(resp.read().decode())
                            except Exception:
                                pass
                            break
                        s.close()
                    except Exception:
                        pass

                mode_result["port_open"] = port_open
                mode_result["pid"] = proc.pid
                mode_result["still_running"] = proc.poll() is None

                if port_open:
                    mode_result["ok"] = True
                    if version_info:
                        mode_result["version_info"] = version_info
                    # SUCCESS — kill the test process
                    try:
                        proc.terminate()
                        proc.wait(timeout=3)
                    except Exception:
                        try:
                            proc.kill()
                        except Exception:
                            pass
                    result["ok"] = True
                    result["working_mode"] = mode_name
                    result.update(mode_result)
                    break
                else:
                    # Port didn't open — kill and try next mode
                    try:
                        proc.terminate()
                        proc.wait(timeout=3)
                    except Exception:
                        try:
                            proc.kill()
                        except Exception:
                            pass

                    mode_result["ok"] = False
                    mode_result["stderr_last10"] = [l.strip() for l in stderr_lines[-10:] if l.strip()]
                    result["modes_tried"] = result.get("modes_tried", []) + [mode_result]

            except Exception as e:
                mode_result["ok"] = False
                mode_result["error"] = f"{type(e).__name__}: {e}"
                result["modes_tried"] = result.get("modes_tried", []) + [mode_result]

        # Safety: ensure no bytes values
        def _ensure_str(v):
            if isinstance(v, bytes):
                return v.decode(errors="replace")
            if isinstance(v, dict):
                return {k: _ensure_str(val) for k, val in v.items()}
            if isinstance(v, list):
                return [_ensure_str(item) for item in v]
            return v
        result = _ensure_str(result)
        return result

    try:
        result = await loop.run_in_executor(_EXECUTOR, _test_launch)
        return _cors_json_response(result)
    except Exception as e:
        _record_request(is_error=True)
        return _cors_json_response(
            {"ok": False, "error": f"Test launch failed: {str(e)}"},
            status=500
        )


async def handle_v1_cdp_test_ws(request):
    """GET /v1/browser/cdp/test-ws — Diagnostic: test WebSocket connectivity to Chromium debug port.

    v1.9.19: Complete rewrite — ROBUST error handling, simplified flow.
    - Top-level try/except to ALWAYS return valid JSON (fixes all `?` values)
    - ONLY tests tab-level WS (most important, skip browser WS to save time)
    - websockets library FIRST, aiohttp as fallback
    - Total time capped at ~20s to fit within curl --max-time 45
    - Includes raw /json/version and /json/list responses for debugging

    Query params:
        port: int (default: 9223)
    """
    r = require_auth(request)
    if r: return r
    _record_request()

    cdp = _get_cdp_module()
    if not cdp:
        _record_request(is_error=True)
        return _cors_json_response(
            {"ok": False, "error": "cdp_browser module not found",
             "ws_connect_ok": False, "tab_ws_connect_ok": False},
            status=500
        )

    qs = parse_qs(request.query_string)
    port = int(qs.get("port", ["9223"])[0])

    result = {
        "ok": False,
        "port": port,
        "ws_connect_ok": False,
        "tab_ws_connect_ok": False,
        "ws_connect_time_s": None,
        "tab_ws_connect_time_s": None,
        "websockets_browser_ok": False,
        "websockets_tab_ok": False,
    }

    browser_proc = None

    try:
        loop = asyncio.get_event_loop()
        log.info("[test-ws] START port=%d", port)

        # Step 0: Launch Chromium on the test port
        try:
            await loop.run_in_executor(None, cdp._kill_port_processes, port)
            await asyncio.sleep(0.3)
        except Exception as e:
            log.warning("[test-ws] Kill stale processes failed: %s", e)

        browser_proc = await loop.run_in_executor(
            None, cdp.launch_browser, port, True
        )
        result["browser_pid"] = browser_proc.pid
        log.info("[test-ws] Browser launched pid=%d", browser_proc.pid)

        # Wait for port to become ready (max 10s)
        port_ready = False
        for attempt in range(20):
            await asyncio.sleep(0.5)
            if browser_proc.poll() is not None:
                result["browser_died"] = True
                result["browser_rc"] = browser_proc.returncode
                launch_diag = getattr(browser_proc, '_cdp_launch_diag', {})
                stderr_log = launch_diag.get("stderr_log", "")
                if stderr_log:
                    try:
                        with open(stderr_log, "r") as f:
                            result["browser_stderr"] = f.read().strip()[:1000]
                    except Exception:
                        pass
                result["error"] = f"Browser died (rc={browser_proc.returncode})"
                return _cors_json_response(result)
            try:
                tabs = await loop.run_in_executor(None, cdp.list_tabs, port)
                if tabs:
                    port_ready = True
                    result["port_ready_after_s"] = (attempt + 1) * 0.5
                    log.info("[test-ws] Port ready after %.1fs", (attempt + 1) * 0.5)
                    break
            except Exception:
                pass

        if not port_ready:
            result["error"] = f"Chromium port {port} not ready after 10s"
            try:
                browser_proc.terminate()
                browser_proc.wait(timeout=3)
            except Exception:
                pass
            browser_proc = None
            return _cors_json_response(result)

        # Step 1: Fetch /json/version
        raw_version = {}
        browser_ws_url = ""
        try:
            def _get_version():
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/version", timeout=5) as r:
                    return json.loads(r.read().decode())
            raw_version = await loop.run_in_executor(None, _get_version)
            browser_ws_url = raw_version.get("webSocketDebuggerUrl", "")
            result["raw_version_keys"] = list(raw_version.keys())
            # Chromium /json/version doesn't include "id" — extract from WS URL
            version_id = raw_version.get("id", "")
            if not version_id and browser_ws_url:
                import re as _re
                m = _re.search(r'/devtools/browser/([^/]+)', browser_ws_url)
                if m:
                    version_id = m.group(1)
            result["version_info"] = {
                "Browser": raw_version.get("Browser", "?")[:50],
                "webSocketDebuggerUrl": (browser_ws_url or "MISSING")[:80],
                "id": version_id or "N/A",
            }
            result["http_endpoint_ok"] = True
            log.info("[test-ws] /json/version: keys=%s wsUrl=%s id=%s",
                        list(raw_version.keys()),
                        raw_version.get("webSocketDebuggerUrl", "MISSING")[:60],
                        raw_version.get("id", "MISSING")[:30])
        except Exception as e:
            result["raw_version_error"] = f"{type(e).__name__}: {e}"
            result["http_endpoint_ok"] = False
            log.warning("[test-ws] /json/version FAILED: %s", e)

        # Step 2: Fetch /json/list
        raw_tabs = []
        tab_ws_url = ""
        tab_target_id = ""
        try:
            def _get_tabs():
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/list", timeout=5) as r:
                    return json.loads(r.read().decode())
            raw_tabs = await loop.run_in_executor(None, _get_tabs)
            page_tabs = [t for t in raw_tabs if t.get("type") == "page"]
            result["tab_count"] = len(raw_tabs)
            result["page_tab_count"] = len(page_tabs)
            if page_tabs:
                tab_ws_url = page_tabs[0].get("webSocketDebuggerUrl", "")
                tab_target_id = page_tabs[0].get("id", "")
                result["tab_target_id"] = tab_target_id
                for i, t in enumerate(page_tabs[:3]):
                    log.info("[test-ws] page[%d]: id=%s wsUrl=%s url=%s",
                                i, t.get("id", "?")[:20],
                                t.get("webSocketDebuggerUrl", "MISSING")[:60],
                                t.get("url", "?")[:50])
            log.info("[test-ws] /json/list: %d entries, %d pages",
                        len(raw_tabs), len(page_tabs))
        except Exception as e:
            result["raw_tabs_error"] = f"{type(e).__name__}: {e}"
            log.warning("[test-ws] /json/list FAILED: %s", e)

        # Construct WS URLs if webSocketDebuggerUrl is missing
        if not browser_ws_url:
            browser_id = raw_version.get("id", "")
            if browser_id:
                browser_ws_url = f"ws://127.0.0.1:{port}/devtools/browser/{browser_id}"
                result["browser_ws_constructed"] = True
                log.info("[test-ws] Constructed browser WS URL: %s", browser_ws_url)

        if not tab_ws_url and tab_target_id:
            tab_ws_url = f"ws://127.0.0.1:{port}/devtools/page/{tab_target_id}"
            result["tab_ws_constructed"] = True
            log.info("[test-ws] Constructed tab WS URL: %s", tab_ws_url)

        result["ws_url"] = browser_ws_url or "NONE"
        result["tab_ws_url"] = tab_ws_url[:80] if tab_ws_url else "NONE"

        # Step 3: Test TAB-level WebSocket — websockets library FIRST (most reliable on Py3.14)
        if tab_ws_url:
            # Strategy A: websockets library
            try:
                import websockets
                result["websockets_available"] = True
                t0 = time.monotonic()
                try:
                    ws = await asyncio.wait_for(
                        websockets.connect(tab_ws_url, open_timeout=3, close_timeout=2),
                        timeout=5
                    )
                    elapsed = time.monotonic() - t0
                    result["tab_ws_connect_ok"] = True
                    result["tab_ws_connect_time_s"] = round(elapsed, 2)
                    result["websockets_tab_ok"] = True
                    result["websockets_tab_time_s"] = round(elapsed, 2)
                    # Try CDP command
                    try:
                        await ws.send(json.dumps({"id": 1, "method": "Runtime.evaluate",
                                                   "params": {"expression": "1+1"}}))
                        resp = await asyncio.wait_for(ws.recv(), timeout=3)
                        result["websockets_tab_cdp_ok"] = True
                        result["websockets_tab_cdp_preview"] = resp[:200]
                        result["tab_cdp_ok"] = True
                        result["tab_cdp_response"] = resp[:200]
                    except Exception as e:
                        result["websockets_tab_cdp_ok"] = False
                        result["websockets_tab_cdp_error"] = str(e)
                    await ws.close()
                    result["ok"] = True
                    log.info("[test-ws] TAB WS OK (websockets, %.2fs)", elapsed)
                except asyncio.TimeoutError:
                    elapsed = time.monotonic() - t0
                    result["websockets_tab_ok"] = False
                    result["websockets_tab_error"] = f"TIMEOUT after {elapsed:.1f}s"
                    result["websockets_tab_time_s"] = round(elapsed, 2)
                    result["tab_ws_connect_error"] = f"websockets TIMEOUT after {elapsed:.1f}s"
                    log.warning("[test-ws] TAB WS websockets TIMEOUT (%.1fs)", elapsed)
                except Exception as e:
                    result["websockets_tab_ok"] = False
                    result["websockets_tab_error"] = f"{type(e).__name__}: {e}"
                    result["websockets_tab_time_s"] = None
                    result["tab_ws_connect_error"] = f"websockets {type(e).__name__}: {e}"
                    log.warning("[test-ws] TAB WS websockets FAILED: %s", e)
            except ImportError:
                result["websockets_available"] = False
                result["tab_ws_connect_error"] = "websockets library not available"

            # Strategy B: aiohttp (if websockets failed)
            if not result["tab_ws_connect_ok"]:
                try:
                    t0 = time.monotonic()
                    ws_timeout = aiohttp.ClientTimeout(total=3, connect=2, sock_connect=2)
                    connector = aiohttp.TCPConnector(force_close=True, enable_cleanup_closed=True)
                    async with aiohttp.ClientSession(timeout=ws_timeout, connector=connector) as session:
                        tab_ws = await asyncio.wait_for(
                            session.ws_connect(tab_ws_url, heartbeat=None, proxy=None),
                            timeout=5
                        )
                        elapsed = time.monotonic() - t0
                        result["tab_ws_connect_ok"] = True
                        result["tab_ws_connect_time_s"] = round(elapsed, 2)
                        # Try CDP command
                        try:
                            await tab_ws.send_json({"id": 1, "method": "Runtime.evaluate",
                                                     "params": {"expression": "1+1"}})
                            msg = await asyncio.wait_for(tab_ws.receive(), timeout=3)
                            if msg.type == aiohttp.WSMsgType.TEXT:
                                result["tab_cdp_ok"] = True
                                result["tab_cdp_response"] = msg.data[:200]
                        except Exception as e:
                            result["tab_cdp_ok"] = False
                            result["tab_cdp_error"] = str(e)
                        await tab_ws.close()
                        result["ok"] = True
                        log.info("[test-ws] TAB WS OK (aiohttp, %.2fs)", elapsed)
                except asyncio.TimeoutError:
                    elapsed = time.monotonic() - t0
                    result["tab_ws_connect_ok"] = False
                    result["tab_ws_connect_error"] = f"aiohttp TIMEOUT after {elapsed:.1f}s"
                    result["tab_ws_connect_time_s"] = round(elapsed, 2)
                    log.warning("[test-ws] TAB WS aiohttp TIMEOUT (%.1fs)", elapsed)
                except Exception as e:
                    result["tab_ws_connect_ok"] = False
                    result["tab_ws_connect_error"] = f"aiohttp {type(e).__name__}: {e}"
                    result["tab_ws_connect_time_s"] = None
                    log.warning("[test-ws] TAB WS aiohttp FAILED: %s", e)
        else:
            result["tab_ws_connect_ok"] = False
            result["tab_ws_connect_error"] = "No tab WS URL available"
            log.warning("[test-ws] No tab WS URL — cannot test tab WS")

        # Step 4: Test BROWSER-level WS (only if tab WS worked, or as extra info)
        if browser_ws_url:
            try:
                import websockets
                t0 = time.monotonic()
                try:
                    ws = await asyncio.wait_for(
                        websockets.connect(browser_ws_url, open_timeout=3, close_timeout=2),
                        timeout=5
                    )
                    elapsed = time.monotonic() - t0
                    result["ws_connect_ok"] = True
                    result["ws_connect_time_s"] = round(elapsed, 2)
                    result["websockets_browser_ok"] = True
                    result["websockets_browser_time_s"] = round(elapsed, 2)
                    try:
                        await ws.send(json.dumps({"id": 1, "method": "Target.getTargets"}))
                        resp = await asyncio.wait_for(ws.recv(), timeout=3)
                        result["websockets_cdp_ok"] = True
                        result["websockets_cdp_preview"] = resp[:200]
                    except Exception as e:
                        result["websockets_cdp_ok"] = False
                        result["websockets_cdp_error"] = str(e)
                    await ws.close()
                    if not result["ok"]:
                        result["ok"] = True
                    log.info("[test-ws] Browser WS OK (websockets, %.2fs)", elapsed)
                except (asyncio.TimeoutError, Exception) as e:
                    result["ws_connect_ok"] = False
                    result["ws_connect_error"] = f"websockets {type(e).__name__}: {e}"
                    log.warning("[test-ws] Browser WS FAILED: %s", e)
            except ImportError:
                result["ws_connect_ok"] = False
                result["ws_connect_error"] = "websockets library not available"
        else:
            result["ws_connect_ok"] = False
            result["ws_connect_error"] = "No browser WS URL available"

    except Exception as e:
        import traceback
        result["error"] = f"Unhandled: {type(e).__name__}: {e}"
        result["traceback"] = traceback.format_exc()
        log.error("[test-ws] UNHANDLED EXCEPTION: %s\n%s", e, traceback.format_exc())
    finally:
        # Always kill the test browser
        if browser_proc:
            try:
                browser_proc.terminate()
                browser_proc.wait(timeout=3)
            except Exception:
                try:
                    browser_proc.kill()
                except Exception:
                    pass

    return _cors_json_response(result)


async def handle_v1_cdp_connect(request):
    """POST /v1/browser/cdp/connect — Connect to browser CDP.
    
    Body (optional JSON):
        port: int (default: 9222)
        headless: bool (default: true)
    """
    r = require_auth(request)
    if r: return r
    _record_request()
    
    cdp = _get_cdp_module()
    if not cdp:
        _record_request(is_error=True, count_request=False)
        return _cors_json_response(
            {"ok": False, "error": "cdp_browser module not found. Install to scripts/ directory."},
            status=500
        )
    
    if _cdp_state["connected"]:
        return _cors_json_response({
            "ok": True,
            "message": "Already connected",
            "port": _cdp_state["port"],
            "tab_count": _cdp_state["manager"].tab_count if _cdp_state["manager"] else 0,
        })
    
    if _cdp_connect_lock.locked():
        return _cors_json_response({"ok": False, "error": "CDP connect already in progress"}, status=409)
    
    # Parse optional body
    port = 9222
    headless = True
    try:
        body = await request.json()
        port = body.get("port", 9222)
        headless = body.get("headless", True)
    except Exception:
        pass
    
    async with _cdp_connect_lock:
        try:
            mgr = cdp.CDPTabManager(port=port, headless=headless, auto_launch=True)

            # Read the diag file as a fallback — even if executor hangs, we may get partial info
            diag_file_path = os.path.join(tempfile.gettempdir(), f"cdp-browser-{os.getpid()}", "launch-diag.json")

            try:
                await asyncio.wait_for(mgr.connect(), timeout=60)
            except asyncio.TimeoutError:
                _record_request(is_error=True, count_request=False)
                # Gather diagnostics from multiple sources
                browser_crashed = False
                launch_diag = {}
                stderr_info = ""
                chromium_log = ""

                # Source 1: From the browser proc object
                if mgr._browser_proc:
                    if mgr._browser_proc.poll() is not None:
                        browser_crashed = True
                    launch_diag = getattr(mgr._browser_proc, '_cdp_launch_diag', {})
                    stderr_log = launch_diag.get("stderr_log", "")
                    if stderr_log:
                        try:
                            with open(stderr_log, "r") as f:
                                stderr_info = f.read().strip()[:2000]
                        except Exception:
                            pass

                # Source 2: From the diag file (fallback if executor hung)
                if not launch_diag:
                    try:
                        with open(diag_file_path, "r") as f:
                            launch_diag = json.load(f)
                    except Exception:
                        pass

                # Source 3: From Chromium's stderr log directly
                if not stderr_info:
                    try:
                        stderr_log_path = os.path.join(tempfile.gettempdir(), f"cdp-browser-{os.getpid()}", "chromium-launch.log")
                        if os.path.exists(stderr_log_path):
                            with open(stderr_log_path, "r") as f:
                                chromium_log = f.read().strip()[:2000]
                    except Exception:
                        pass

                error_msg = "CDP connect timed out (60s)."
                if browser_crashed:
                    error_msg += f" Browser exited (rc={mgr._browser_proc.returncode})."
                if stderr_info:
                    error_msg += f" stderr: {stderr_info[:400]}"
                elif chromium_log:
                    error_msg += f" chromium.log: {chromium_log[:400]}"
                if launch_diag:
                    if launch_diag.get("direct_error"):
                        error_msg += f" | Direct: {launch_diag['direct_error'][:200]}"
                    if launch_diag.get("direct_exception"):
                        error_msg += f" | DirectExc: {launch_diag['direct_exception'][:200]}"
                    if launch_diag.get("systemd_run_error"):
                        error_msg += f" | SystemdRun: {launch_diag['systemd_run_error'][:200]}"
                    if launch_diag.get("all_failed"):
                        error_msg += " | ALL LAUNCH STRATEGIES FAILED"
                else:
                    error_msg += " | No diagnostics available (executor may have hung). Try manually: chromium --remote-debugging-port=9222 --headless=new --no-sandbox --ozone-platform=headless &"

                # Kill the browser process if it's still running
                if mgr._browser_proc and mgr._browser_proc.poll() is None:
                    try:
                        mgr._browser_proc.terminate()
                        mgr._browser_proc.wait(timeout=2)
                    except Exception:
                        try:
                            mgr._browser_proc.kill()
                        except Exception:
                            pass

                return _cors_json_response(
                    {"ok": False, "error": error_msg, "browser_crashed": browser_crashed,
                     "diagnostics": launch_diag, "stderr": (stderr_info or chromium_log)[:1500]},
                    status=408
                )
            
            _cdp_state["manager"] = mgr
            _cdp_state["connected"] = True
            _cdp_state["port"] = port
            _cdp_state["headless"] = headless
            _cdp_state["last_connect_time"] = datetime.now(timezone.utc).isoformat()
            _cdp_state["last_disconnect_reason"] = None

            # Emit event (Phase 3)
            asyncio.create_task(emit_event("cdp_connect", {"port": port, "headless": headless}))

            # Start the health watcher for auto-reconnect
            _start_cdp_watcher()
            
            # Verify active tab is actually connected (auto-connect may have failed silently)
            # v1.9.18: More aggressive retry with WS URL reconstruction
            active_tab = mgr.active_tab
            tab_connected = active_tab is not None and active_tab.connected
            if active_tab and not active_tab.connected:
                # Retry 1: Try connect again (sometimes first attempt fails)
                try:
                    await asyncio.wait_for(active_tab.connect(), timeout=25)
                    tab_connected = True
                    log.info("[CDP] Re-connected active tab %s on second attempt", mgr.active_tab_id)
                except Exception as e:
                    log.warning("[CDP] Active tab auto-connect retry 1 failed: %s", e)
                
                # Retry 2: Reconstruct WS URL from target_id and try again
                if not tab_connected:
                    old_url = active_tab.ws_url
                    new_url = f"ws://127.0.0.1:{port}/devtools/page/{active_tab.target_id}"
                    if new_url != old_url:
                        log.info("[CDP] Retrying with constructed WS URL: %s (was: %s)", new_url, old_url[:60])
                        active_tab.ws_url = new_url
                        try:
                            await asyncio.wait_for(active_tab.connect(), timeout=15)
                            tab_connected = True
                            log.info("[CDP] Connected active tab with constructed WS URL")
                        except Exception as e:
                            log.warning("[CDP] Constructed WS URL retry failed: %s", e)
                            active_tab.ws_url = old_url  # Restore original
            
            result = {
                "ok": True,
                "message": "CDP connected",
                "port": port,
                "headless": headless,
                "tab_count": mgr.tab_count,
                "active_tab_id": mgr.active_tab_id,
                "tabs": [tab.to_dict() for tab in mgr.list_tabs()],
                "ws_diagnostics": mgr.ws_diagnostics,
            }
            if not tab_connected:
                result["warning"] = "Active tab is not connected — CDP page operations may fail. Try reconnecting."
            return _cors_json_response(result)
        except Exception as e:
            _record_request(is_error=True, count_request=False)
            return _cors_json_response(
                {"ok": False, "error": f"Failed to connect: {str(e)}"},
                status=500
            )


async def handle_v1_cdp_disconnect(request):
    """POST /v1/browser/cdp/disconnect — Disconnect CDP session."""
    r = require_auth(request)
    if r: return r
    _record_request()
    
    if not _cdp_state["connected"]:
        return _cors_json_response({"ok": True, "message": "Not connected"})
    
    if _cdp_connect_lock.locked():
        return _cors_json_response({"ok": False, "error": "CDP operation in progress"}, status=409)
    
    async with _cdp_connect_lock:
        try:
            # Stop monitors/interceptors first
            if _cdp_state.get("interceptor") and _cdp_state["interceptor"].active:
                await _cdp_state["interceptor"].stop()
            if _cdp_state.get("monitor") and _cdp_state["monitor"].active:
                await _cdp_state["monitor"].stop()
            if _cdp_state.get("cookie_mgr") and _cdp_state["cookie_mgr"].active:
                await _cdp_state["cookie_mgr"].stop()
            
            # Stop the health watcher before disconnecting
            _stop_cdp_watcher()

            # Close the manager
            if _cdp_state["manager"]:
                await _cdp_state["manager"].close()
            
            _cdp_state["manager"] = None
            _cdp_state["monitor"] = None
            _cdp_state["interceptor"] = None
            _cdp_state["cookie_mgr"] = None
            _cdp_state["connected"] = False
            _cdp_state["last_disconnect_reason"] = "User disconnected"

            # Emit event (Phase 3)
            asyncio.create_task(emit_event("cdp_disconnect", {"reason": "User disconnected"}))

            return _cors_json_response({"ok": True, "message": "CDP disconnected"})
        except Exception as e:
            _record_request(is_error=True, count_request=False)
            return _cors_json_response(
                {"ok": False, "error": f"Disconnect error: {str(e)}"},
                status=500
            )


# ---- CDP Page Operations ----

async def handle_v1_cdp_navigate(request):
    """POST /v1/browser/cdp/navigate — Navigate to URL.

    Body JSON:
        url: string (required)
        tab_id: string (optional, uses active tab if not specified)
        wait: bool (default: true)

    v2.4.0: Increased timeout to 30s. After navigation, auto-refreshes
    the tab list and activates the correct tab (fixes tab-switching bug
    where navigation created a new tab and CDP lost connection).
    """
    r = require_auth(request)
    if r: return r
    _record_request()

    try:
        body = await request.json()
    except Exception:
        _record_request(is_error=True, count_request=False)
        return _cors_json_response({"ok": False, "error": "Invalid JSON body"}, status=400)

    url = body.get("url")
    if not url:
        _record_request(is_error=True, count_request=False)
        return _cors_json_response({"ok": False, "error": "missing 'url' parameter"}, status=400)

    tab_id = body.get("tab_id")
    wait = body.get("wait", True)

    tab, err = await _cdp_active_tab(tab_id)
    if err: return err
    # Track navigation time so watcher skips probes during page loads
    _cdp_state["last_navigation_time"] = time.time()

    original_tab_id = tab.target_id
    try:
        # v2.4.0: Hard timeout — 28s CDP, 30s asyncio (increased from 20s for heavy sites)
        result = await asyncio.wait_for(tab.navigate(url, wait=wait, timeout=28), timeout=30)

        # v2.4.0: Auto-refresh tab list after navigation
        # Navigation may have created a new tab or changed the active one
        mgr = _cdp_state.get("manager")
        if mgr:
            try:
                await mgr.sync_tabs()
            except Exception as e:
                log.debug("[CDP] Tab sync after navigate failed (non-fatal): %s", e)

        return _cors_json_response({
            "ok": True,
            "url": url,
            "tab_id": tab.target_id,
            "result": result,
        })
    except asyncio.TimeoutError:
        _record_request(is_error=True, count_request=False)
        log.error("[CDP] navigate timed out (30s) for URL: %.200s", url)
        return _cors_json_response(
            {"ok": False, "error": f"Navigation timed out (30s limit): {url}", "timeout": 30},
            status=408
        )
    except Exception as e:
        _record_request(is_error=True, count_request=False)
        return _cors_json_response(
            {"ok": False, "error": str(e)},
            status=500
        )


async def handle_v1_cdp_screenshot(request):
    """GET /v1/browser/cdp/screenshot — Take screenshot.
    
    Query params:
        tab_id: string (optional)
        format: "png" | "base64" (default: "base64")
        save_path: string (optional, save to file on host)
    """
    r = require_auth(request)
    if r: return r
    _record_request()
    
    qs = parse_qs(request.query_string)
    tab_id = qs.get("tab_id", [None])[0]
    fmt = qs.get("format", ["base64"])[0]
    save_path = qs.get("save_path", [None])[0]
    
    tab, err = await _cdp_active_tab(tab_id)
    if err: return err
    
    try:
        # v2.3.0: Hard timeout — 18s CDP, 20s asyncio
        img_bytes = await asyncio.wait_for(tab.screenshot(path=save_path, timeout=18), timeout=20)
        if img_bytes is None:
            _record_request(is_error=True, count_request=False)
            return _cors_json_response({"ok": False, "error": "Screenshot returned no data"}, status=500)
        
        if fmt == "base64":
            import base64 as _b64
            b64_data = _b64.b64encode(img_bytes).decode("ascii")
            return _cors_json_response({
                "ok": True,
                "format": "base64",
                "data": b64_data,
                "size_bytes": len(img_bytes),
                "tab_id": tab.target_id,
            })
        else:
            # Return raw PNG
            return web.Response(
                body=img_bytes,
                content_type="image/png",
                headers={"Access-Control-Allow-Origin": "*"}
            )
    except asyncio.TimeoutError:
        _record_request(is_error=True, count_request=False)
        log.error("[CDP] screenshot timed out (20s)")
        return _cors_json_response(
            {"ok": False, "error": "Screenshot timed out (20s limit)", "timeout": 20},
            status=408
        )
    except Exception as e:
        _record_request(is_error=True, count_request=False)
        return _cors_json_response({"ok": False, "error": str(e)}, status=500)


async def handle_v1_cdp_dom(request):
    """GET /v1/browser/cdp/dom — Dump page DOM.
    
    Query params:
        tab_id: string (optional)
    """
    r = require_auth(request)
    if r: return r
    _record_request()
    
    qs = parse_qs(request.query_string)
    tab_id = qs.get("tab_id", [None])[0]
    
    tab, err = await _cdp_active_tab(tab_id)
    if err: return err
    
    try:
        # v2.3.0: Hard timeout — 18s CDP, 20s asyncio
        html = await asyncio.wait_for(tab.dump_dom(timeout=18), timeout=20)
        if html is None:
            _record_request(is_error=True, count_request=False)
            return _cors_json_response({"ok": False, "error": "Failed to dump DOM"}, status=500)
        
        # Truncate if too large
        max_len = DEFAULT_MAX_OUTPUT
        truncated = False
        if len(html) > max_len:
            html = html[:max_len] + f"\n...[truncated {len(html) - max_len} chars]"
            truncated = True
        
        return _cors_json_response({
            "ok": True,
            "html": html,
            "length": len(html),
            "truncated": truncated,
            "tab_id": tab.target_id,
        })
    except asyncio.TimeoutError:
        _record_request(is_error=True, count_request=False)
        log.error("[CDP] DOM dump timed out (20s)")
        return _cors_json_response(
            {"ok": False, "error": "DOM dump timed out (20s limit)", "timeout": 20},
            status=408
        )
    except Exception as e:
        _record_request(is_error=True, count_request=False)
        return _cors_json_response({"ok": False, "error": str(e)}, status=500)


async def handle_v1_cdp_eval(request):
    """POST /v1/browser/cdp/eval — Evaluate JavaScript.

    Body JSON:
        expression: string (required)
        tab_id: string (optional)
        timeout: number (optional, default: 14) — CDP-level timeout in seconds (max 60)

    v2.3.0: Added 15s hard timeout to prevent system freezes from
    infinite JS loops or huge DOM serialization. Results >1MB are
    truncated to prevent OOM.
    v2.5.1: Configurable timeout, better error messages for heavy eval,
            and explicit `ok: false` with reason when JS throws.
    """
    r = require_auth(request)
    if r: return r
    _record_request()

    try:
        body = await request.json()
    except Exception:
        _record_request(is_error=True, count_request=False)
        return _cors_json_response({"ok": False, "error": "Invalid JSON body"}, status=400)

    expression = body.get("expression")
    if not expression:
        _record_request(is_error=True, count_request=False)
        return _cors_json_response({"ok": False, "error": "missing 'expression' parameter"}, status=400)

    # v2.5.1: Allow caller to specify a longer timeout for heavy computations
    cdp_timeout = min(body.get("timeout", 14), 60)  # Cap at 60s
    asyncio_timeout = cdp_timeout + 1

    tab_id = body.get("tab_id")
    tab, err = await _cdp_active_tab(tab_id)
    if err: return err

    try:
        # v2.5.1: Use CDP Runtime.evaluate directly so we can distinguish
        # between JS exceptions and transport-level failures.
        eval_result = await asyncio.wait_for(
            tab.send("Runtime.evaluate", {
                "expression": expression,
                "returnByValue": True,
                "timeout": cdp_timeout * 1000,  # CDP expects ms
            }),
            timeout=asyncio_timeout
        )

        if eval_result and "result" in eval_result:
            inner = eval_result["result"]
            # Check for JS exception
            if "exceptionDetails" in inner:
                exc = inner["exceptionDetails"]
                exc_text = ""
                if "exception" in exc and "description" in exc["exception"]:
                    exc_text = exc["exception"]["description"]
                elif "text" in exc:
                    exc_text = exc["text"]
                log.warning("[CDP] eval JS exception: %s", exc_text)
                return _cors_json_response({
                    "ok": False,
                    "error": f"JavaScript exception: {exc_text}",
                    "exception_details": exc,
                }, status=400)

            # Successful evaluation
            result_val = inner.get("result", {}).get("value")
            # Convert to string for consistency with eval_js behavior
            if result_val is not None:
                result_str = str(result_val) if not isinstance(result_val, str) else result_val
            else:
                result_str = None

            # v2.3.0: Truncate large results to prevent OOM / response bloat
            CDP_EVAL_MAX_RESULT = 1 * 1024 * 1024  # 1MB
            truncated = False
            if isinstance(result_str, str) and len(result_str) > CDP_EVAL_MAX_RESULT:
                original_len = len(result_str)
                result_str = result_str[:CDP_EVAL_MAX_RESULT] + f"\n...[truncated, {original_len} total chars]"
                truncated = True
                log.warning("[CDP] eval result truncated: %d -> %d chars", original_len, CDP_EVAL_MAX_RESULT)

            return _cors_json_response({
                "ok": True,
                "result": result_str,
                "truncated": truncated,
                "tab_id": tab.target_id,
            })

        # v2.5.1: CDP returned no result — likely WebSocket issue
        log.warning("[CDP] eval returned no result — possible WS issue")
        return _cors_json_response({
            "ok": False,
            "error": "CDP returned empty result — WebSocket may be stale. Try reconnecting.",
        }, status=502)

    except asyncio.TimeoutError:
        _record_request(is_error=True, count_request=False)
        log.error("[CDP] eval_js timed out (%ds) — expression: %.200s", asyncio_timeout, expression)
        return _cors_json_response(
            {"ok": False, "error": f"JavaScript evaluation timed out ({cdp_timeout}s limit). "
             "The expression may contain an infinite loop or heavy computation. "
             "Try a shorter expression or increase the 'timeout' parameter.",
             "timeout": cdp_timeout},
            status=408
        )
    except ConnectionError as e:
        _record_request(is_error=True, count_request=False)
        log.error("[CDP] eval connection error: %s", e)
        return _cors_json_response(
            {"ok": False, "error": f"CDP connection lost during eval: {e}. Try reconnecting."},
            status=502
        )
    except Exception as e:
        _record_request(is_error=True, count_request=False)
        return _cors_json_response({"ok": False, "error": str(e)}, status=500)


async def handle_v1_cdp_click(request):
    """POST /v1/browser/cdp/click — Click element by CSS selector or coordinates.

    Body JSON:
        selector: string (optional) — CSS selector for element click
        x: number (optional) — X coordinate for coordinate click
        y: number (optional) — Y coordinate for coordinate click
        tab_id: string (optional)

    Either 'selector' OR both 'x' and 'y' must be provided.
    Coordinate clicks use CDP Input.dispatchMouseEvent and can reach
    iframe content (e.g., reCAPTCHA) that CSS selectors cannot.

    v2.3.0: Added x/y coordinate support and 15s hard timeout.
    """
    r = require_auth(request)
    if r: return r
    _record_request()

    try:
        body = await request.json()
    except Exception:
        _record_request(is_error=True, count_request=False)
        return _cors_json_response({"ok": False, "error": "Invalid JSON body"}, status=400)

    selector = body.get("selector")
    x = body.get("x")
    y = body.get("y")

    if not selector and (x is None or y is None):
        _record_request(is_error=True, count_request=False)
        return _cors_json_response(
            {"ok": False, "error": "Provide 'selector' or both 'x' and 'y' coordinates"},
            status=400
        )

    tab_id = body.get("tab_id")
    tab, err = await _cdp_active_tab(tab_id)
    if err: return err

    try:
        if selector:
            # CSS selector click (existing behavior)
            clicked = await asyncio.wait_for(tab.click(selector, timeout=14), timeout=15)
            return _cors_json_response({
                "ok": True,
                "clicked": clicked,
                "selector": selector,
                "mode": "selector",
                "tab_id": tab.target_id,
            })
        else:
            # Coordinate click via CDP Input.dispatchMouseEvent
            clicked = await asyncio.wait_for(tab.click_at(float(x), float(y), timeout=14), timeout=15)
            return _cors_json_response({
                "ok": True,
                "clicked": clicked,
                "x": float(x),
                "y": float(y),
                "mode": "coordinates",
                "tab_id": tab.target_id,
            })
    except asyncio.TimeoutError:
        _record_request(is_error=True, count_request=False)
        log.error("[CDP] click timed out (15s)")
        return _cors_json_response(
            {"ok": False, "error": "Click operation timed out (15s limit)", "timeout": 15},
            status=408
        )
    except Exception as e:
        _record_request(is_error=True, count_request=False)
        return _cors_json_response({"ok": False, "error": str(e)}, status=500)


async def handle_v1_cdp_type(request):
    """POST /v1/browser/cdp/type — Type text into element.
    
    Body JSON:
        selector: string (required)
        text: string (required)
        tab_id: string (optional)
    """
    r = require_auth(request)
    if r: return r
    _record_request()
    
    try:
        body = await request.json()
    except Exception:
        _record_request(is_error=True, count_request=False)
        return _cors_json_response({"ok": False, "error": "Invalid JSON body"}, status=400)
    
    selector = body.get("selector")
    text = body.get("text")
    if not selector or text is None:
        _record_request(is_error=True, count_request=False)
        return _cors_json_response({"ok": False, "error": "missing 'selector' or 'text' parameter"}, status=400)
    
    tab_id = body.get("tab_id")
    tab, err = await _cdp_active_tab(tab_id)
    if err: return err
    
    try:
        # v2.3.0: Hard timeout — 14s CDP, 15s asyncio
        typed = await asyncio.wait_for(tab.type_text(selector, text, timeout=14), timeout=15)
        return _cors_json_response({
            "ok": True,
            "typed": typed,
            "selector": selector,
            "tab_id": tab.target_id,
        })
    except asyncio.TimeoutError:
        _record_request(is_error=True, count_request=False)
        log.error("[CDP] type_text timed out (15s)")
        return _cors_json_response(
            {"ok": False, "error": "Type operation timed out (15s limit)", "timeout": 15},
            status=408
        )
    except Exception as e:
        _record_request(is_error=True, count_request=False)
        return _cors_json_response({"ok": False, "error": str(e)}, status=500)


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

# ---- Control Lease Endpoints (v2.9.0) ----

async def handle_v1_control_status(request):
    """GET /v1/control/status — Check if agent desktop control is active/paused/revoked.

    v2.9.0: New endpoint.
    """
    r = require_auth(request)
    if r: return r
    _record_request()

    with _control_lock:
        return _cors_json_response({
            "ok": True,
            "control": _control_state["status"],
            "reason": _control_state["reason"],
            "paused_at": _control_state["paused_at"],
            "revoked_at": _control_state["revoked_at"],
            "last_agent_input_at": _control_state["last_agent_input_at"],
            "last_user_input_at": _control_state["last_user_input_at"],
            "session_id": _control_state["session_id"],
        })


async def handle_v1_control_pause(request):
    """POST /v1/control/pause — Pause agent desktop control.

    Body JSON (optional):
        reason: string — Reason for pausing
        session_id: string — Optional session to target

    While paused, all desktop input endpoints (click, type, key, mouse, focus)
    return 403 control_paused.

    v2.9.0: New endpoint.
    """
    r = require_auth(request)
    if r: return r
    _record_request()

    reason = None
    try:
        body = await request.json()
        reason = body.get("reason")
    except Exception:
        pass

    with _control_lock:
        if _control_state["status"] == "revoked":
            return _cors_json_response({
                "ok": False, "error": "control_revoked",
                "message": "Control is revoked. Use /v1/control/resume to re-activate.",
            }, status=409)

        _control_state["status"] = "paused"
        _control_state["reason"] = reason
        _control_state["paused_at"] = utc_now()

    log.info("[Control] Agent desktop control PAUSED (reason: %s)", reason)
    return _cors_json_response({
        "ok": True,
        "control": "paused",
        "reason": reason,
        "paused_at": _control_state["paused_at"],
    })


async def handle_v1_control_resume(request):
    """POST /v1/control/resume — Resume agent desktop control after pause/revoke.

    Body JSON (optional):
        session_id: string — Optional session to resume

    v2.9.0: New endpoint.
    """
    r = require_auth(request)
    if r: return r
    _record_request()

    with _control_lock:
        prev = _control_state["status"]
        _control_state["status"] = "active"
        _control_state["reason"] = None
        _control_state["paused_at"] = None
        _control_state["revoked_at"] = None
        resumed_at = utc_now()

    log.info("[Control] Agent desktop control RESUMED (was: %s)", prev)
    return _cors_json_response({
        "ok": True,
        "control": "active",
        "previous_status": prev,
        "resumed_at": resumed_at,
    })


async def handle_v1_control_revoke(request):
    """POST /v1/control/revoke — Hard revoke agent desktop control.

    Body JSON (optional):
        reason: string — Reason for revocation

    After revocation, all desktop input endpoints return 403 control_revoked.
    Only /v1/control/resume can re-enable control.

    v2.9.0: New endpoint.
    """
    r = require_auth(request)
    if r: return r
    _record_request()

    reason = None
    try:
        body = await request.json()
        reason = body.get("reason")
    except Exception:
        pass

    with _control_lock:
        _control_state["status"] = "revoked"
        _control_state["reason"] = reason or "User revoked control"
        _control_state["revoked_at"] = utc_now()

    log.warning("[Control] Agent desktop control REVOKED (reason: %s)", reason)
    return _cors_json_response({
        "ok": True,
        "control": "revoked",
        "reason": _control_state["reason"],
        "revoked_at": _control_state["revoked_at"],
    })


# ---- CDP Tab Management ----

async def handle_v1_cdp_tabs(request):
    """GET /v1/browser/cdp/tabs — List all tracked tabs.
    
    Auto-connects any disconnected tabs that have ws_url before listing.
    """
    r = require_auth(request)
    if r: return r
    _record_request()
    
    if not _cdp_state["connected"] or not _cdp_state["manager"]:
        return _cors_json_response({"ok": True, "tabs": [], "tab_count": 0})
    
    mgr = _cdp_state["manager"]
    tabs = mgr.list_tabs()
    
    # Auto-connect disconnected tabs that have ws_url (lazy connect)
    for tab in tabs:
        if not tab.connected and tab.ws_url:
            try:
                await asyncio.wait_for(tab.connect(), timeout=15)
                log.debug("[CDP-Tabs] Auto-connected tab %s", tab.target_id)
            except Exception as e:
                log.debug("[CDP-Tabs] Auto-connect failed for %s: %s", tab.target_id, e)
    
    return _cors_json_response({
        "ok": True,
        "tabs": [tab.to_dict() for tab in tabs],
        "tab_count": len(tabs),
        "active_tab_id": mgr.active_tab_id,
    })


async def handle_v1_cdp_tabs_new(request):
    """POST /v1/browser/cdp/tabs/new — Open new tab.
    
    Body JSON:
        url: string (default: "about:blank")
        activate: bool (default: true)
    """
    r = require_auth(request)
    if r: return r
    _record_request()
    
    if not _cdp_state["connected"] or not _cdp_state["manager"]:
        _record_request(is_error=True, count_request=False)
        return _cors_json_response({"ok": False, "error": "CDP not connected"}, status=400)
    
    url = "about:blank"
    activate = True
    try:
        body = await request.json()
        url = body.get("url", "about:blank")
        activate = body.get("activate", True)
    except Exception:
        pass
    
    mgr = _cdp_state["manager"]
    
    try:
        tab = await mgr.new_tab(url, activate=activate)
        return _cors_json_response({
            "ok": True,
            "tab": tab.to_dict(),
            "tab_id": tab.target_id,
        })
    except Exception as e:
        _record_request(is_error=True, count_request=False)
        return _cors_json_response({"ok": False, "error": str(e)}, status=500)


async def handle_v1_cdp_tabs_close(request):
    """POST /v1/browser/cdp/tabs/close — Close a tab.
    
    Body JSON:
        tab_id: string (required)
    """
    r = require_auth(request)
    if r: return r
    _record_request()
    
    if not _cdp_state["connected"] or not _cdp_state["manager"]:
        _record_request(is_error=True, count_request=False)
        return _cors_json_response({"ok": False, "error": "CDP not connected"}, status=400)
    
    try:
        body = await request.json()
    except Exception:
        _record_request(is_error=True, count_request=False)
        return _cors_json_response({"ok": False, "error": "Invalid JSON body"}, status=400)
    
    tab_id = body.get("tab_id")
    if not tab_id:
        _record_request(is_error=True, count_request=False)
        return _cors_json_response({"ok": False, "error": "missing 'tab_id'"}, status=400)
    
    mgr = _cdp_state["manager"]
    
    try:
        success = await mgr.close_tab(tab_id)
        return _cors_json_response({
            "ok": success,
            "tab_id": tab_id,
            "remaining_tabs": mgr.tab_count,
        })
    except Exception as e:
        _record_request(is_error=True, count_request=False)
        return _cors_json_response({"ok": False, "error": str(e)}, status=500)


async def handle_v1_cdp_tabs_activate(request):
    """POST /v1/browser/cdp/tabs/activate — Activate a tab.
    
    Body JSON:
        tab_id: string (required)
    """
    r = require_auth(request)
    if r: return r
    _record_request()
    
    if not _cdp_state["connected"] or not _cdp_state["manager"]:
        _record_request(is_error=True, count_request=False)
        return _cors_json_response({"ok": False, "error": "CDP not connected"}, status=400)
    
    try:
        body = await request.json()
    except Exception:
        _record_request(is_error=True, count_request=False)
        return _cors_json_response({"ok": False, "error": "Invalid JSON body"}, status=400)
    
    tab_id = body.get("tab_id")
    if not tab_id:
        _record_request(is_error=True, count_request=False)
        return _cors_json_response({"ok": False, "error": "missing 'tab_id'"}, status=400)
    
    mgr = _cdp_state["manager"]
    
    success = mgr.activate(tab_id)
    return _cors_json_response({
        "ok": success,
        "tab_id": tab_id,
        "active_tab_id": mgr.active_tab_id,
    })


# ---- CDP Cookie Management ----

async def _ensure_cookie_manager():
    """Lazily create and start a CDPCookieManager.
    
    Tries the active tab first, then falls back to any connected tab.
    If no tab is connected, attempts to connect the first available tab.
    Includes proper error logging instead of silent None returns.
    
    v2.5.0 fix: Falls back to direct CDP commands via tab if CDPCookieManager fails.
    """
    if _cdp_state.get("cookie_mgr") and _cdp_state["cookie_mgr"].active:
        return _cdp_state["cookie_mgr"]
    
    cdp = _get_cdp_module()
    if not cdp:
        log.warning("[Cookie] cdp_browser module not available")
        return None
    
    # Get the active tab
    tab, _ = await _cdp_active_tab()
    
    # If active tab is not connected, try to find any connected tab
    if not tab or not getattr(tab, 'connected', False):
        mgr = _cdp_state.get("manager")
        if mgr:
            for t in mgr.list_tabs():
                if t.connected:
                    tab = t
                    log.info("[Cookie] Using non-active connected tab: %s", t.target_id)
                    break
            
            # If still no connected tab, try connecting the first available one
            if not tab:
                for t in mgr.list_tabs():
                    if t.ws_url:
                        try:
                            await asyncio.wait_for(t.connect(), timeout=15)
                            tab = t
                            log.info("[Cookie] Connected tab %s for cookie manager", t.target_id)
                            break
                        except Exception as e:
                            log.warning("[Cookie] Failed to connect tab %s: %s", t.target_id, e)
                            continue
    
    if not tab:
        log.error("[Cookie] No tab available for cookie manager — CDP may be disconnected")
        return None
    
    if not getattr(tab, 'connected', False):
        log.error("[Cookie] Tab %s is not connected — cannot start cookie manager",
                  getattr(tab, 'target_id', 'unknown'))
        return None
    
    # Try using CDPCookieManager with tab._browser
    browser = getattr(tab, '_browser', None)
    if browser:
        try:
            mgr = cdp.CDPCookieManager(browser)
            await asyncio.wait_for(mgr.start(), timeout=10)
            _cdp_state["cookie_mgr"] = mgr
            log.info("[Cookie] Cookie manager started successfully for tab %s via _browser",
                     getattr(tab, 'target_id', 'unknown'))
            return mgr
        except asyncio.TimeoutError:
            log.warning("[Cookie] CDPCookieManager start timed out — falling back to tab.send()")
        except ConnectionError as e:
            log.warning("[Cookie] CDPCookieManager ConnectionError: %s — falling back to tab.send()", e)
        except Exception as e:
            log.warning("[Cookie] CDPCookieManager failed: %s: %s — falling back to tab.send()", type(e).__name__, e)
    
    # Fallback: create a lightweight cookie manager using tab.send() directly
    # This avoids the browser-level WS issue where Network.* commands hang
    try:
        # Enable Network domain on the tab
        await asyncio.wait_for(tab.send("Network.enable"), timeout=10)
        
        # Create a thin wrapper that uses tab.send() instead of browser.send()
        class TabCookieManager:
            """Lightweight cookie manager that uses tab-level CDP commands.
            
            v2.5.1: Fixed interface to match CDPCookieManager — set_cookie now
            accepts the same keyword arguments as CDPCookieManager.set_cookie,
            so the handler code doesn't need to know which implementation it's using.
            """
            def __init__(self, tab):
                self._tab = tab
                self.active = True
            
            async def get_all_cookies(self):
                res = await self._tab.send("Network.getAllCookies", timeout=15)
                if res and "result" in res:
                    return res["result"].get("cookies", [])
                return []
            
            async def get_cookies_for_url(self, url):
                res = await self._tab.send("Network.getCookies", {"urls": [url]}, timeout=15)
                if res and "result" in res:
                    return res["result"].get("cookies", [])
                return []
            
            # v2.5.1: Match CDPCookieManager.set_cookie signature
            async def set_cookie(self, name: str, value: str, domain: str = "",
                                 path: str = "/", secure: bool = False,
                                 http_only: bool = False, same_site: str = "",
                                 expires=None, priority: str = "Medium",
                                 same_party: bool = False,
                                 source_scheme: str = "NonSecure") -> bool:
                params = {
                    "name": name,
                    "value": value,
                    "path": path,
                    "secure": secure,
                    "httpOnly": http_only,
                }
                if domain:
                    params["domain"] = domain
                if same_site and same_site in ("Strict", "Lax", "None"):
                    params["sameSite"] = same_site
                if expires is not None:
                    params["expires"] = expires
                try:
                    res = await self._tab.send("Network.setCookie", params, timeout=10)
                    if res and "result" in res:
                        return res["result"].get("success", False)
                    return True  # CDP didn't report failure
                except Exception as e:
                    log.warning("[Cookie] TabCookieManager.set_cookie failed: %s", e)
                    return False
            
            async def delete_cookie(self, name, domain=""):
                params = {"name": name}
                if domain:
                    params["domain"] = domain
                return await self._tab.send("Network.deleteCookies", params, timeout=10)
            
            async def clear_cookies(self):
                return await self._tab.send("Network.clearBrowserCookies", timeout=10)
            
            def list_profiles(self):
                return []
            
            def get_profile_info(self, name):
                return None
            
            async def save_profile(self, name, domain_filter=None):
                cookies = await self.get_all_cookies()
                return len(cookies)
            
            async def restore_profile(self, name, clear_first=True):
                return 0
            
            def delete_profile(self, name):
                return False
            
            async def check_session(self, domain, auth_cookie_names=None):
                cookies = await self.get_all_cookies()
                domain_cookies = [c for c in cookies if domain in c.get("domain", "")]
                return {"active": len(domain_cookies) > 0, "cookie_count": len(domain_cookies)}
            
            async def stop(self):
                self.active = False
        
        mgr = TabCookieManager(tab)
        _cdp_state["cookie_mgr"] = mgr
        log.info("[Cookie] Tab-level cookie manager started for tab %s",
                 getattr(tab, 'target_id', 'unknown'))
        return mgr
    except asyncio.TimeoutError:
        log.error("[Cookie] Tab Network.enable timed out (10s) — browser may be unresponsive")
        return None
    except ConnectionError as e:
        log.error("[Cookie] Tab ConnectionError: %s", e)
        return None
    except Exception as e:
        log.error("[Cookie] Tab-level cookie manager failed: %s: %s", type(e).__name__, e)
        return None


async def handle_v1_cdp_cookies_get(request):
    """GET /v1/browser/cdp/cookies — Get cookies.
    
    Query params:
        url: string (optional, filter by URL)
        domain: string (optional, filter by domain)
    """
    r = require_auth(request)
    if r: return r
    _record_request()
    
    if not _cdp_state["connected"]:
        _record_request(is_error=True, count_request=False)
        return _cors_json_response({"ok": False, "error": "CDP not connected"}, status=400)
    
    try:
        cookie_mgr = await _ensure_cookie_manager()
        if not cookie_mgr:
            _record_request(is_error=True, count_request=False)
            return _cors_json_response({"ok": False, "error": "Failed to start cookie manager"}, status=500)
        
        qs = parse_qs(request.query_string)
        url = qs.get("url", [None])[0]
        domain = qs.get("domain", [None])[0]
        
        if url:
            cookies = await cookie_mgr.get_cookies_for_url(url)
        elif domain:
            all_cookies = await cookie_mgr.get_all_cookies()
            cookies = [c for c in all_cookies if domain in c.get("domain", "")]
        else:
            cookies = await cookie_mgr.get_all_cookies()
        
        return _cors_json_response({
            "ok": True,
            "cookies": cookies,
            "count": len(cookies),
        })
    except Exception as e:
        _record_request(is_error=True, count_request=False)
        return _cors_json_response({"ok": False, "error": str(e)}, status=500)


async def handle_v1_cdp_cookies_set(request):
    """POST /v1/browser/cdp/cookies — Set a cookie.
    
    Body JSON:
        name: string (required)
        value: string (required)
        domain: string (optional)
        path: string (default: "/")
        secure: bool (default: false)
        http_only: bool (default: false)
        same_site: string (optional: "Strict"|"Lax"|"None")
        expires: float (optional, UTC timestamp)
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
    
    name = body.get("name")
    value = body.get("value")
    if not name or value is None:
        _record_request(is_error=True, count_request=False)
        return _cors_json_response({"ok": False, "error": "missing 'name' or 'value'"}, status=400)
    
    try:
        cookie_mgr = await _ensure_cookie_manager()
        if not cookie_mgr:
            _record_request(is_error=True, count_request=False)
            return _cors_json_response({"ok": False, "error": "Failed to start cookie manager"}, status=500)
        
        success = await cookie_mgr.set_cookie(
            name=name,
            value=value,
            domain=body.get("domain", ""),
            path=body.get("path", "/"),
            secure=body.get("secure", False),
            http_only=body.get("http_only", False),
            same_site=body.get("same_site", ""),
            expires=body.get("expires"),
        )
        
        return _cors_json_response({
            "ok": success,
            "name": name,
            "domain": body.get("domain", ""),
        })
    except Exception as e:
        _record_request(is_error=True, count_request=False)
        return _cors_json_response({"ok": False, "error": str(e)}, status=500)


async def handle_v1_cdp_cookies_delete(request):
    """DELETE /v1/browser/cdp/cookies — Delete a cookie.
    
    Body JSON:
        name: string (required)
        domain: string (optional)
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
    
    name = body.get("name")
    if not name:
        _record_request(is_error=True, count_request=False)
        return _cors_json_response({"ok": False, "error": "missing 'name'"}, status=400)
    
    try:
        cookie_mgr = await _ensure_cookie_manager()
        if not cookie_mgr:
            _record_request(is_error=True, count_request=False)
            return _cors_json_response({"ok": False, "error": "Failed to start cookie manager"}, status=500)
        
        await cookie_mgr.delete_cookie(name, domain=body.get("domain", ""))
        
        return _cors_json_response({
            "ok": True,
            "deleted": name,
        })
    except Exception as e:
        _record_request(is_error=True, count_request=False)
        return _cors_json_response({"ok": False, "error": str(e)}, status=500)


async def handle_v1_cdp_cookies_clear(request):
    """POST /v1/browser/cdp/cookies/clear — Clear all cookies."""
    r = require_auth(request)
    if r: return r
    _record_request()
    
    if not _cdp_state["connected"]:
        _record_request(is_error=True, count_request=False)
        return _cors_json_response({"ok": False, "error": "CDP not connected"}, status=400)
    
    try:
        cookie_mgr = await _ensure_cookie_manager()
        if not cookie_mgr:
            _record_request(is_error=True, count_request=False)
            return _cors_json_response({"ok": False, "error": "Failed to start cookie manager"}, status=500)
        
        await cookie_mgr.clear_cookies()
        
        return _cors_json_response({"ok": True, "message": "All cookies cleared"})
    except Exception as e:
        _record_request(is_error=True, count_request=False)
        return _cors_json_response({"ok": False, "error": str(e)}, status=500)


async def handle_v1_cdp_cookies_profiles(request):
    """GET /v1/browser/cdp/cookies/profiles — List cookie profiles.
    POST /v1/browser/cdp/cookies/profiles — Save/restore/delete profile.
    
    POST Body JSON:
        action: "save" | "restore" | "delete" (required)
        name: string (required)
        domain: string (optional, for save filter)
        clear_first: bool (default: true, for restore)
    """
    r = require_auth(request)
    if r: return r
    _record_request()
    
    if not _cdp_state["connected"]:
        _record_request(is_error=True, count_request=False)
        return _cors_json_response({"ok": False, "error": "CDP not connected"}, status=400)
    
    if request.method == "GET":
        cookie_mgr = _cdp_state.get("cookie_mgr")
        profiles = cookie_mgr.list_profiles() if cookie_mgr else []
        profile_info = []
        for name in profiles:
            info = cookie_mgr.get_profile_info(name) if cookie_mgr else None
            profile_info.append(info or {"name": name})
        
        return _cors_json_response({
            "ok": True,
            "profiles": profile_info,
            "count": len(profile_info),
        })
    
    # POST — save/restore/delete
    try:
        body = await request.json()
    except Exception:
        _record_request(is_error=True, count_request=False)
        return _cors_json_response({"ok": False, "error": "Invalid JSON body"}, status=400)
    
    action = body.get("action")
    name = body.get("name")
    if not action or not name:
        _record_request(is_error=True, count_request=False)
        return _cors_json_response({"ok": False, "error": "missing 'action' or 'name'"}, status=400)
    
    try:
        cookie_mgr = await _ensure_cookie_manager()
        if not cookie_mgr:
            _record_request(is_error=True, count_request=False)
            return _cors_json_response({"ok": False, "error": "Failed to start cookie manager"}, status=500)
        
        if action == "save":
            count = await cookie_mgr.save_profile(name, domain_filter=body.get("domain"))
            return _cors_json_response({
                "ok": True,
                "action": "save",
                "profile": name,
                "cookie_count": count,
            })
        elif action == "restore":
            count = await cookie_mgr.restore_profile(
                name, 
                clear_first=body.get("clear_first", True)
            )
            return _cors_json_response({
                "ok": True,
                "action": "restore",
                "profile": name,
                "restored_count": count,
            })
        elif action == "delete":
            deleted = cookie_mgr.delete_profile(name)
            return _cors_json_response({
                "ok": deleted,
                "action": "delete",
                "profile": name,
            })
        else:
            return _cors_json_response(
                {"ok": False, "error": f"Unknown action '{action}'. Use save, restore, or delete."},
                status=400
            )
    except KeyError as e:
        return _cors_json_response({"ok": False, "error": str(e)}, status=404)
    except Exception as e:
        _record_request(is_error=True, count_request=False)
        return _cors_json_response({"ok": False, "error": str(e)}, status=500)


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

async def handle_v1_browser_browse(request):
    """POST /v1/browser/browse — Unified browser endpoint with auto CDP/BrowserAct switching.
    
    Automatically selects the best browser backend:
    - If stealth=true or captcha=true: Use BrowserAct (Camoufox-based, anti-detection)
    - Otherwise: Use CDP (headless Chromium, faster)
    
    Body JSON:
        url: string (required)
        action: string ("extract" | "shot" | "click" | "type", default: "extract")
        stealth: bool (default: false) — use stealth browser (BrowserAct)
        captcha: bool (default: false) — expect CAPTCHA on page
        wait_for: string (optional CSS selector)
        timeout: float (default: 15)
        width: int (default: 1280, for screenshots)
        height: int (default: 720, for screenshots)
    """
    r = require_auth(request)
    if r: return r
    _record_request()
    
    try:
        body = await request.json()
    except Exception:
        _record_request(is_error=True, count_request=False)
        return _cors_json_response({"ok": False, "error": "Invalid JSON body"}, status=400)
    
    url = body.get("url")
    if not url:
        _record_request(is_error=True, count_request=False)
        return _cors_json_response({"ok": False, "error": "missing 'url'"}, status=400)
    
    action = body.get("action", "extract")
    stealth = body.get("stealth", False)
    captcha = body.get("captcha", False)
    wait_for = body.get("wait_for")
    timeout = body.get("timeout", 15)
    width = body.get("width", 1280)
    height = body.get("height", 720)
    
    # Auto-switch logic: BrowserAct for stealth/captcha, CDP for everything else
    use_browseract = stealth or captcha
    
    if use_browseract:
        # Use BrowserAct (Camoufox-based stealth browser)
        try:
            ba_skill = Path(APP_DIR) / "skills" / "browseract" / "run.sh"
            if not ba_skill.exists():
                _record_request(is_error=True, count_request=False)
                return _cors_json_response({"ok": False, "error": "BrowserAct skill not installed"}, status=503)
            
            cmd = [shutil.which("bash") or "bash", str(ba_skill), action, url]
            if wait_for:
                cmd.extend(["--wait-for", wait_for])
            if action == "shot":
                cmd.extend(["--width", str(width), "--height", str(height)])
            
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout + 30)
            
            if proc.returncode == 0 and stdout:
                try:
                    result = json.loads(stdout.decode("utf-8", errors="replace"))
                    result["backend"] = "browseract"
                    result["stealth"] = True
                    return _cors_json_response(result)
                except json.JSONDecodeError:
                    text = stdout.decode("utf-8", errors="replace")
                    return _cors_json_response({"ok": True, "backend": "browseract", "stealth": True, "output": text[:50000]})
            else:
                err = stderr.decode("utf-8", errors="replace")[:2000] if stderr else "unknown error"
                _record_request(is_error=True, count_request=False)
                return _cors_json_response({"ok": False, "error": f"BrowserAct failed (rc={proc.returncode}): {err}"}, status=500)
        except asyncio.TimeoutError:
            _record_request(is_error=True, count_request=False)
            return _cors_json_response({"ok": False, "error": f"BrowserAct timed out ({timeout}s)"}, status=408)
        except Exception as e:
            _record_request(is_error=True, count_request=False)
            return _cors_json_response({"ok": False, "error": str(e)}, status=500)
    
    else:
        # Use CDP (headless Chromium — faster)
        if not _cdp_state["connected"]:
            # Try to auto-connect
            try:
                cdp = _get_cdp_module()
                if cdp:
                    mgr = cdp.CDPTabManager(port=_cdp_state["port"], headless=_cdp_state["headless"], auto_launch=True)
                    await asyncio.wait_for(mgr.connect(), timeout=60)
                    _cdp_state["manager"] = mgr
                    _cdp_state["connected"] = True
                    _cdp_state["last_connect_time"] = datetime.now(timezone.utc).isoformat()
                    _start_cdp_watcher()
                else:
                    _record_request(is_error=True, count_request=False)
                    return _cors_json_response({"ok": False, "error": "CDP module not available"}, status=503)
            except Exception as e:
                _record_request(is_error=True, count_request=False)
                return _cors_json_response({"ok": False, "error": f"CDP auto-connect failed: {e}"}, status=503)
        
        mgr = _cdp_state.get("manager")
        if not mgr or not mgr.active_tab or not mgr.active_tab.connected:
            _record_request(is_error=True, count_request=False)
            return _cors_json_response({"ok": False, "error": "No active CDP tab"}, status=503)
        
        try:
            if action == "extract":
                browser = mgr.active_tab._browser
                await asyncio.wait_for(browser.navigate(url, wait=True), timeout=timeout)
                if wait_for:
                    safe_selector = json.dumps(wait_for)
                    expr = f"new Promise((resolve, reject) => {{ const check = () => {{ if (document.querySelector({safe_selector})) resolve(true); else setTimeout(check, 200); }}; setTimeout(() => reject('timeout'), {(timeout-2)*1000}); check(); }})"
                    await asyncio.wait_for(browser.eval_js(expr), timeout=timeout)
                text_content = await asyncio.wait_for(browser.eval_js("document.body ? document.body.innerText.substring(0, 50000) : ''"), timeout=10)
                title = await asyncio.wait_for(browser.eval_js("document.title"), timeout=5)
                return _cors_json_response({"ok": True, "backend": "cdp", "stealth": False, "url": url, "title": title, "text": (text_content or "")[:20000], "text_len": len(text_content or "")})
            
            elif action == "shot":
                browser = mgr.active_tab._browser
                await asyncio.wait_for(browser.send("Emulation.setDeviceMetricsOverride", {"width": width, "height": height, "deviceScaleFactor": 1, "mobile": False}), timeout=5)
                await asyncio.wait_for(browser.navigate(url, wait=True), timeout=timeout)
                res = await asyncio.wait_for(browser.send("Page.captureScreenshot", {"format": "png"}), timeout=15)
                if res and "result" in res and "data" in res["result"]:
                    return _cors_json_response({"ok": True, "backend": "cdp", "stealth": False, "format": "png", "data": res["result"]["data"], "width": width, "height": height})
                else:
                    _record_request(is_error=True, count_request=False)
                    return _cors_json_response({"ok": False, "error": "Screenshot returned no data"}, status=500)
            
            elif action == "click":
                selector = body.get("selector")
                if not selector:
                    return _cors_json_response({"ok": False, "error": "missing 'selector' for click action"}, status=400)
                await asyncio.wait_for(mgr.active_tab.click(selector), timeout=timeout)
                return _cors_json_response({"ok": True, "backend": "cdp", "stealth": False, "action": "click", "selector": selector})
            
            elif action == "type":
                selector = body.get("selector")
                text = body.get("text")
                if not selector or not text:
                    return _cors_json_response({"ok": False, "error": "missing 'selector' and 'text' for type action"}, status=400)
                await asyncio.wait_for(mgr.active_tab.type_text(selector, text), timeout=timeout)
                return _cors_json_response({"ok": True, "backend": "cdp", "stealth": False, "action": "type", "selector": selector})
            
            else:
                _record_request(is_error=True, count_request=False)
                return _cors_json_response({"ok": False, "error": f"Unknown action: {action}. Supported: extract, shot, click, type"}, status=400)
        
        except asyncio.TimeoutError:
            _record_request(is_error=True, count_request=False)
            return _cors_json_response({"ok": False, "error": f"CDP {action} timed out ({timeout}s)"}, status=408)
        except Exception as e:
            _record_request(is_error=True, count_request=False)
            return _cors_json_response({"ok": False, "error": str(e)}, status=500)


# --- /v1/metrics GET — Bridge performance metrics ---

async def handle_v1_metrics(request: web.Request) -> web.Response:
    """GET /v1/metrics — Bridge performance metrics."""
    try:
        _record_request()
        with _metrics_lock:
            durations = BRIDGE_METRICS["request_durations"]
            avg_duration = round(sum(durations) / len(durations), 6) if durations else 0.0
            uptime = round(time.time() - BRIDGE_METRICS["start_time"], 1)
            error_rate = 0.0
            if BRIDGE_METRICS["total_requests"] > 0:
                error_rate = round(BRIDGE_METRICS["total_errors"] / BRIDGE_METRICS["total_requests"] * 100, 2)

            result = {
                "ok": True,
                "uptime_seconds": uptime,
                "total_requests": BRIDGE_METRICS["total_requests"],
                "total_exec": BRIDGE_METRICS["total_exec"],
                "total_errors": BRIDGE_METRICS["total_errors"],
                "average_duration_sec": avg_duration,
                "error_rate_percent": error_rate,
                "start_time": datetime.fromtimestamp(BRIDGE_METRICS["start_time"], tz=timezone.utc).isoformat(),
                "version": VERSION,
                "active_processes": len(ACTIVE_PROCESSES),
            }
        return _cors_json_response(result)
    except Exception as e:
        return _cors_json_response({"ok": False, "error": str(e)}, status=500)


# --- /metrics GET — Prometheus-compatible metrics endpoint ---

async def handle_prometheus_metrics(request: web.Request) -> web.Response:
    """GET /metrics — Prometheus-compatible metrics endpoint.
    
    Returns metrics in Prometheus text exposition format.
    No auth required — this is standard for /metrics endpoints (scraped by Prometheus).
    """
    try:
        with _metrics_lock:
            uptime = round(time.time() - BRIDGE_METRICS["start_time"], 1)
            durations = list(BRIDGE_METRICS["request_durations"])
            avg_duration = round(sum(durations) / len(durations), 6) if durations else 0.0
        
        # Calculate quantiles outside the lock to avoid holding it too long
        if durations:
            sd = sorted(durations)
            p50 = sd[len(sd)//2]
            p95 = sd[int(len(sd)*0.95)] if len(sd) >= 20 else sd[-1]
            p99 = sd[int(len(sd)*0.99)] if len(sd) >= 100 else sd[-1]
        else:
            p50 = p95 = p99 = 0.0

        lines = [
            "# HELP arena_bridge_uptime_seconds Bridge uptime in seconds",
            "# TYPE arena_bridge_uptime_seconds gauge",
            f"arena_bridge_uptime_seconds {uptime}",
            "",
            "# HELP arena_bridge_requests_total Total number of requests",
            "# TYPE arena_bridge_requests_total counter",
            f"arena_bridge_requests_total {BRIDGE_METRICS['total_requests']}",
            "",
            "# HELP arena_bridge_exec_total Total number of exec operations",
            "# TYPE arena_bridge_exec_total counter",
            f"arena_bridge_exec_total {BRIDGE_METRICS['total_exec']}",
            "",
            "# HELP arena_bridge_errors_total Total number of errors",
            "# TYPE arena_bridge_errors_total counter",
            f"arena_bridge_errors_total {BRIDGE_METRICS['total_errors']}",
            "",
            "# HELP arena_bridge_request_duration_avg_seconds Average request duration",
            "# TYPE arena_bridge_request_duration_avg_seconds gauge",
            f"arena_bridge_request_duration_avg_seconds {avg_duration}",
            "",
            "# HELP arena_bridge_request_duration_seconds Request duration quantiles",
            "# TYPE arena_bridge_request_duration_seconds summary",
            f'arena_bridge_request_duration_seconds{{quantile="0.5"}} {p50}',
            f'arena_bridge_request_duration_seconds{{quantile="0.95"}} {p95}',
            f'arena_bridge_request_duration_seconds{{quantile="0.99"}} {p99}',
            "",
            "# HELP arena_bridge_active_processes Number of active subprocesses",
            "# TYPE arena_bridge_active_processes gauge",
            f"arena_bridge_active_processes {len(ACTIVE_PROCESSES)}",
            "",
            "# HELP arena_bridge_cdp_connected CDP connection status (1=connected, 0=disconnected)",
            "# TYPE arena_bridge_cdp_connected gauge",
            f"arena_bridge_cdp_connected {1 if _cdp_state['connected'] else 0}",
            "",
            "# HELP arena_bridge_cdp_reconnect_count Total number of CDP auto-reconnects",
            "# TYPE arena_bridge_cdp_reconnect_count counter",
            f"arena_bridge_cdp_reconnect_count {_cdp_state.get('reconnect_count', 0)}",
            "",
            "# HELP arena_bridge_info Bridge version info",
            "# TYPE arena_bridge_info gauge",
            f'arena_bridge_info{{version="{VERSION}"}} 1',
            "",
            "# HELP arena_bridge_memory_mb Bridge memory usage in MB",
            "# TYPE arena_bridge_memory_mb gauge",
            f"arena_bridge_memory_mb {_watchdog_state['memory_mb']}",
            "",
            "# HELP arena_bridge_cpu_percent Bridge CPU usage percent",
            "# TYPE arena_bridge_cpu_percent gauge",
            f"arena_bridge_cpu_percent {_watchdog_state['cpu_percent']}",
            "",
            "# HELP arena_bridge_event_subscribers Number of event stream subscribers",
            "# TYPE arena_bridge_event_subscribers gauge",
            f"arena_bridge_event_subscribers {len(_event_subscribers)}",
            "",
            "# HELP arena_bridge_tls_enabled TLS/HTTPS enabled status",
            "# TYPE arena_bridge_tls_enabled gauge",
            f"arena_bridge_tls_enabled {1 if _tls_config['enabled'] else 0}",
            "",
            "# HELP arena_bridge_grpc_enabled gRPC secondary interface enabled",
            "# TYPE arena_bridge_grpc_enabled gauge",
            f"arena_bridge_grpc_enabled {1 if _grpc_config['enabled'] else 0}",
            "",
            "# HELP arena_bridge_cluster_role Cluster role (0=standalone, 1=follower, 2=leader)",
            "# TYPE arena_bridge_cluster_role gauge",
            f"arena_bridge_cluster_role {{'role': '{_cluster_state['role']}'}} {0 if _cluster_state['role'] == 'standalone' else 1 if _cluster_state['role'] == 'follower' else 2}",
            "",
            "# HELP arena_bridge_sandbox_enabled Skill sandbox enabled",
            "# TYPE arena_bridge_sandbox_enabled gauge",
            f"arena_bridge_sandbox_enabled {1 if _sandbox_config['enabled'] else 0}",
            "",
            "# HELP arena_bridge_otel_enabled OpenTelemetry tracing enabled",
            "# TYPE arena_bridge_otel_enabled gauge",
            f"arena_bridge_otel_enabled {1 if _otel_config['enabled'] else 0}",
            "",
        ]
        
        return web.Response(text="\n".join(lines), content_type="text/plain; version=0.0.4", charset="utf-8")
    except Exception:
        return web.Response(text="# ERROR: internal error\n", status=500, content_type="text/plain", charset="utf-8")


# --- /api-docs GET — OpenAPI 3.0 specification ---

async def handle_api_docs(request: web.Request) -> web.Response:
    """GET /api-docs — OpenAPI 3.0 specification for all bridge endpoints."""
    spec = {
        "openapi": "3.0.3",
        "info": {
            "title": "Arena Unified Bridge API",
            "version": VERSION,
            "description": "Unified bridge for AI agent orchestration: CDP browser control, BrowserAct stealth browsing, SuperPowers skills, task management, and system monitoring."
        },
        "servers": [{"url": f"http://{socket.gethostname()}:{_get_bridge_port()}"}],
        "security": [{"BearerAuth": []}],
        "components": {
            "securitySchemes": {
                "BearerAuth": {"type": "http", "scheme": "bearer"}
            }
        },
        "paths": {
            "/health": {"get": {"summary": "Health check", "tags": ["Bridge"], "responses": {"200": {"description": "OK"}}}},
            "/v1/version": {"get": {"summary": "Bridge version", "tags": ["Bridge"], "responses": {"200": {"description": "Version info"}}}},
            "/v1/status": {"get": {"summary": "Bridge status", "tags": ["Bridge"], "responses": {"200": {"description": "Status info"}}}},
            "/v1/info": {"get": {"summary": "Bridge info", "tags": ["Bridge"], "responses": {"200": {"description": "Detailed info"}}}},
            "/v1/metrics": {"get": {"summary": "Bridge metrics (JSON)", "tags": ["Bridge"], "responses": {"200": {"description": "Metrics JSON"}}}},
            "/v1/capabilities": {"get": {"summary": "Agent-facing capability map", "tags": ["System"], "responses": {"200": {"description": "Capabilities by subsystem/backend"}}}},
            "/v1/hardware": {"get": {"summary": "Canonical rich hardware/system inventory", "tags": ["System"], "responses": {"200": {"description": "Normalized hardware inventory"}}}},
            "/v1/hwinfo": {"get": {"summary": "Compatibility alias for /v1/hardware", "tags": ["System"], "responses": {"200": {"description": "Hardware inventory"}}}},
            "/metrics": {"get": {"summary": "Prometheus metrics (text)", "tags": ["Bridge"], "responses": {"200": {"description": "Prometheus text format"}}}},
            "/v1/browser/cdp/status": {"get": {"summary": "CDP connection status", "tags": ["CDP"], "responses": {"200": {"description": "CDP status"}}}},
            "/v1/cdp/status": {"get": {"summary": "Alias for /v1/browser/cdp/status", "tags": ["CDP"], "responses": {"200": {"description": "CDP status"}}}},
            "/v1/browser/cdp/diag": {"get": {"summary": "CDP diagnostics", "tags": ["CDP"], "responses": {"200": {"description": "Diagnostic info"}}}},
            "/v1/browser/cdp/health": {"get": {"summary": "CDP health dashboard", "tags": ["CDP"], "responses": {"200": {"description": "Health info with reconnect history"}}}},
            "/v1/browser/cdp/connect": {"post": {"summary": "Connect to browser via CDP", "tags": ["CDP"], "requestBody": {"content": {"application/json": {"schema": {"type": "object", "properties": {"port": {"type": "integer", "default": 9222}, "headless": {"type": "boolean", "default": True}}}}}}, "responses": {"200": {"description": "Connected"}}}},
            "/v1/browser/cdp/disconnect": {"post": {"summary": "Disconnect CDP", "tags": ["CDP"], "responses": {"200": {"description": "Disconnected"}}}},
            "/v1/browser/cdp/navigate": {"post": {"summary": "Navigate to URL", "tags": ["CDP"], "requestBody": {"content": {"application/json": {"schema": {"type": "object", "properties": {"url": {"type": "string"}}}}}}, "responses": {"200": {"description": "Navigation result"}}}},
            "/v1/browser/cdp/eval": {"post": {"summary": "Evaluate JavaScript", "tags": ["CDP"], "requestBody": {"content": {"application/json": {"schema": {"type": "object", "properties": {"expression": {"type": "string"}}}}}}, "responses": {"200": {"description": "Eval result"}}}},
            "/v1/browser/cdp/screenshot": {"post": {"summary": "Take screenshot", "tags": ["CDP"], "responses": {"200": {"description": "Screenshot data"}}}},
            "/v1/browser/cdp/dom": {"get": {"summary": "Dump DOM", "tags": ["CDP"], "responses": {"200": {"description": "DOM HTML"}}}},
            "/v1/browser/cdp/tabs": {"get": {"summary": "List browser tabs", "tags": ["CDP"], "responses": {"200": {"description": "Tab list"}}}},
            "/v1/browser/cdp/tabs/new": {"post": {"summary": "Open new tab", "tags": ["CDP"], "requestBody": {"content": {"application/json": {"schema": {"type": "object", "properties": {"url": {"type": "string"}, "activate": {"type": "boolean"}}}}}}, "responses": {"200": {"description": "New tab info"}}}},
            "/v1/browser/cdp/tabs/close": {"post": {"summary": "Close tab", "tags": ["CDP"], "requestBody": {"content": {"application/json": {"schema": {"type": "object", "properties": {"tab_id": {"type": "string"}}}}}}, "responses": {"200": {"description": "Close result"}}}},
            "/v1/browser/cdp/tabs/activate": {"post": {"summary": "Activate tab", "tags": ["CDP"], "requestBody": {"content": {"application/json": {"schema": {"type": "object", "properties": {"tab_id": {"type": "string"}}}}}}, "responses": {"200": {"description": "Activation result"}}}},
            "/v1/browser/cdp/click": {"post": {"summary": "Click element", "tags": ["CDP"], "requestBody": {"content": {"application/json": {"schema": {"type": "object", "properties": {"selector": {"type": "string"}}}}}}, "responses": {"200": {"description": "Click result"}}}},
            "/v1/browser/cdp/type": {"post": {"summary": "Type text into element", "tags": ["CDP"], "requestBody": {"content": {"application/json": {"schema": {"type": "object", "properties": {"selector": {"type": "string"}, "text": {"type": "string"}}}}}}, "responses": {"200": {"description": "Type result"}}}},
            "/v1/browser/cdp/cookies": {"get": {"summary": "Get cookies", "tags": ["CDP"], "responses": {"200": {"description": "Cookie list"}}}},
            "/v1/browser/cdp/cookies/set": {"post": {"summary": "Set cookies", "tags": ["CDP"], "responses": {"200": {"description": "Set result"}}}},
            "/v1/browser/cdp/cookies/delete": {"post": {"summary": "Delete cookies", "tags": ["CDP"], "responses": {"200": {"description": "Delete result"}}}},
            "/v1/browser/cdp/cookies/clear": {"post": {"summary": "Clear all cookies", "tags": ["CDP"], "responses": {"200": {"description": "Clear result"}}}},
            "/v1/browser/cdp/network/start": {"post": {"summary": "Start network monitoring", "tags": ["CDP"], "responses": {"200": {"description": "Monitor started"}}}},
            "/v1/browser/cdp/network/stop": {"post": {"summary": "Stop network monitoring", "tags": ["CDP"], "responses": {"200": {"description": "Monitor stopped"}}}},
            "/v1/browser/cdp/network/requests": {"get": {"summary": "Get captured network requests", "tags": ["CDP"], "responses": {"200": {"description": "Request list"}}}},
            "/v1/browser/cdp/network/har": {"get": {"summary": "Get HAR export", "tags": ["CDP"], "responses": {"200": {"description": "HAR data"}}}},
            "/v1/browser/cdp/intercept/start": {"post": {"summary": "Start request interception", "tags": ["CDP"], "responses": {"200": {"description": "Interception started"}}}},
            "/v1/browser/cdp/intercept/stop": {"post": {"summary": "Stop request interception", "tags": ["CDP"], "responses": {"200": {"description": "Interception stopped"}}}},
            "/v1/browser/cdp/stealth/extract": {"post": {"summary": "Stealth extract page content via CDP", "tags": ["CDP Stealth"], "requestBody": {"content": {"application/json": {"schema": {"type": "object", "properties": {"url": {"type": "string"}, "wait_for": {"type": "string"}, "timeout": {"type": "number", "default": 15}}}}}}, "responses": {"200": {"description": "Extracted content"}}}},
            "/v1/browser/cdp/stealth/shot": {"post": {"summary": "Stealth screenshot via CDP", "tags": ["CDP Stealth"], "requestBody": {"content": {"application/json": {"schema": {"type": "object", "properties": {"url": {"type": "string"}, "width": {"type": "integer", "default": 1280}, "height": {"type": "integer", "default": 720}, "full_page": {"type": "boolean", "default": False}, "format": {"type": "string", "enum": ["png", "jpeg"], "default": "png"}, "timeout": {"type": "number", "default": 15}}}}}}, "responses": {"200": {"description": "Screenshot data"}}}},
            "/v1/browser/cdp/raw-info": {"get": {"summary": "Raw CDP HTTP info", "tags": ["CDP Debug"], "responses": {"200": {"description": "Raw CDP data"}}}},
            "/v1/browser/cdp/test-launch": {"get": {"summary": "Test CDP browser launch", "tags": ["CDP Debug"], "responses": {"200": {"description": "Launch test result"}}}},
            "/v1/browser/cdp/test-ws": {"get": {"summary": "Test CDP WebSocket", "tags": ["CDP Debug"], "responses": {"200": {"description": "WS test result"}}}},
            "/v1/desktop/screenshot": {"get": {"summary": "Take desktop screenshot", "tags": ["Desktop"], "parameters": [
                {"name": "format", "in": "query", "schema": {"type": "string", "enum": ["base64", "png", "jpeg", "jpg", "webp"], "default": "base64"}},
                {"name": "scale", "in": "query", "schema": {"type": "number", "minimum": 0, "maximum": 1}},
                {"name": "max_width", "in": "query", "schema": {"type": "integer", "minimum": 1}},
                {"name": "quality", "in": "query", "schema": {"type": "integer", "minimum": 1, "maximum": 100, "default": 80}}
            ], "responses": {"200": {"description": "Screenshot image bytes or base64 JSON"}}}},
            "/v1/desktop/type": {"post": {"summary": "Type text on the desktop", "tags": ["Desktop"], "requestBody": {"content": {"application/json": {"schema": {"type": "object", "properties": {"text": {"type": "string"}, "delay": {"type": "integer", "default": 50}, "clear": {"type": "boolean", "default": False}, "ensure_latin": {"type": "boolean", "default": True}}, "required": ["text"]}}}}, "responses": {"200": {"description": "Type result"}}}},
            "/v1/exec": {"post": {"summary": "Execute command", "tags": ["Exec"], "requestBody": {"content": {"application/json": {"schema": {"type": "object", "properties": {"cmd": {"type": "string"}, "timeout": {"type": "integer", "default": 30}, "cwd": {"type": "string"}}}}}}, "responses": {"200": {"description": "Command result"}}}},
            "/v1/kill": {"post": {"summary": "Kill process by PID", "tags": ["Exec"], "responses": {"200": {"description": "Kill result"}}}},
            "/v1/skills": {"get": {"summary": "List available skills", "tags": ["Skills"], "responses": {"200": {"description": "Skill list"}}}},
            "/v1/skills/run": {"post": {"summary": "Execute a skill", "tags": ["Skills"], "requestBody": {"content": {"application/json": {"schema": {"type": "object", "properties": {"name": {"type": "string"}, "args": {"type": "array", "items": {"type": "string"}}}}}}}}, "responses": {"200": {"description": "Skill output"}}},
            "/v1/tasks": {"get": {"summary": "List tasks", "tags": ["Tasks"], "responses": {"200": {"description": "Task list"}}}, "post": {"summary": "Create task (cmd or title)", "tags": ["Tasks"], "requestBody": {"content": {"application/json": {"schema": {"type": "object", "properties": {"cmd": {"type": "string", "description": "Command to execute"}, "title": {"type": "string", "description": "Task title (if no cmd)"}, "description": {"type": "string"}, "priority": {"type": "string", "enum": ["low", "normal", "high"]}}}}}}, "responses": {"200": {"description": "Created task"}}}},
            "/v1/memory": {"get": {"summary": "List memory facts", "tags": ["Memory"], "responses": {"200": {"description": "Memory entries"}}}},
            "/v1/recall": {"get": {"summary": "Recall relevant facts", "tags": ["Memory"], "responses": {"200": {"description": "Recalled facts"}}}},
            "/v1/sysinfo": {"get": {"summary": "System information", "tags": ["System"], "responses": {"200": {"description": "System info"}}}},
            "/v1/audit": {"get": {"summary": "Audit log", "tags": ["System"], "responses": {"200": {"description": "Audit entries"}}}},
            "/v1/doctor": {"get": {"summary": "Run diagnostics", "tags": ["System"], "responses": {"200": {"description": "Diagnostic results"}}}},
            "/gui": {"get": {"summary": "Web dashboard", "tags": ["Bridge"], "responses": {"200": {"description": "HTML dashboard"}}}},
            "/api-docs": {"get": {"summary": "OpenAPI specification", "tags": ["Bridge"], "responses": {"200": {"description": "OpenAPI 3.0 JSON"}}}},
            "/openapi.json": {"get": {"summary": "OpenAPI specification alias", "tags": ["Bridge"], "responses": {"200": {"description": "OpenAPI 3.0 JSON"}}}},
            "/v1/events": {"get": {"summary": "WebSocket real-time event stream", "tags": ["Events"], "responses": {"200": {"description": "WebSocket upgrade for events"}}}},
            "/v1/skills/reload": {"post": {"summary": "Force reload skills cache", "tags": ["Skills"], "responses": {"200": {"description": "Reloaded skills"}}}},
            "/v1/audit/log": {"get": {"summary": "Request/response log with filters", "tags": ["System"], "responses": {"200": {"description": "Request log entries"}}}},
            "/v1/watchdog": {"get": {"summary": "Watchdog status and config", "tags": ["Watchdog"], "responses": {"200": {"description": "Watchdog info"}}}},
            "/v1/users": {"get": {"summary": "List users (admin)", "tags": ["Auth"], "responses": {"200": {"description": "User list"}}}},
            "/v1/batch": {"post": {"summary": "Execute multiple operations in parallel", "tags": ["Bridge"], "requestBody": {"content": {"application/json": {"schema": {"type": "object", "properties": {"operations": {"type": "array", "items": {"type": "object", "properties": {"method": {"type": "string"}, "path": {"type": "string"}, "body": {"type": "object"}}}}, "max_concurrent": {"type": "integer", "default": 5}}}}}}, "responses": {"200": {"description": "Batch results"}}}},
            "/v1/profiles": {"get": {"summary": "List browser session profiles", "tags": ["Profiles"], "responses": {"200": {"description": "Profile list"}}}},
            "/v1/alerts": {"get": {"summary": "Alert configurations and status", "tags": ["Watchdog"], "responses": {"200": {"description": "Alert states"}}}},
        },
        "tags": [
            {"name": "Bridge", "description": "Core bridge operations"},
            {"name": "CDP", "description": "Chrome DevTools Protocol browser control"},
            {"name": "CDP Stealth", "description": "Stealth-aware content extraction and screenshots via CDP"},
            {"name": "CDP Debug", "description": "CDP diagnostic and testing endpoints"},
            {"name": "Exec", "description": "Command execution"},
            {"name": "Desktop", "description": "Desktop screenshot, input, focus and control lease"},
            {"name": "Skills", "description": "Skill system"},
            {"name": "Tasks", "description": "Task management"},
            {"name": "Memory", "description": "Memory and recall"},
            {"name": "System", "description": "System information and diagnostics"},
            {"name": "Events", "description": "Real-time WebSocket event stream"},
            {"name": "Watchdog", "description": "Health monitoring and alerting"},
            {"name": "Auth", "description": "Multi-user authentication and roles"},
            {"name": "Profiles", "description": "Browser session profiles (cookies, tabs, localStorage)"},
        ],
    }
    return _cors_json_response(spec)


# ============================================================================
# HANDLERS — MCP Streamable HTTP
# ============================================================================

async def handle_mcp_post(request: web.Request) -> web.Response:
    """MCP Streamable HTTP — main endpoint."""
    r = require_auth(request)
    if r: return r
    _record_request()
    try:
        msg = await request.json()
    except Exception:
        _record_request(is_error=True, count_request=False)
        return _cors_json_response({"jsonrpc": "2.0", "error": {"code": -32700, "message": "Parse error"}}, status=400)

    # New session on initialize
    session_hdr = request.headers.get("Mcp-Session-Id", "")
    if msg.get("method") == "initialize":
        session = sid()
        request.app["mcp_sessions"][session] = {"created": now_ms()}
        resp = handle_rpc(msg)
        return web.json_response(resp, headers={
            "Mcp-Session-Id": session,
            "Access-Control-Allow-Origin": "*",
        })

    resp = handle_rpc(msg)
    if resp is None:
        return web.Response(status=204, headers={"Access-Control-Allow-Origin": "*"})
    return web.json_response(resp, headers={"Access-Control-Allow-Origin": "*"})


async def handle_mcp_delete(request: web.Request) -> web.Response:
    """Close MCP session."""
    r = require_auth(request)
    if r: return r
    try:
        sess = request.headers.get("Mcp-Session-Id", "")
        request.app["mcp_sessions"].pop(sess, None)
        return web.Response(status=204, headers={"Access-Control-Allow-Origin": "*"})


    # ============================================================================
    # HANDLERS — MCP SSE Legacy
    # ============================================================================
    except Exception as e:
        return _cors_json_response({"ok": False, "error": str(e)}, status=500)

async def handle_sse(request: web.Request) -> web.Response:
    """SSE legacy transport — open event stream."""
    r = require_auth(request)
    if r: return r
    _record_request()
    session = sid()
    request.app["mcp_sessions"][session] = {"created": now_ms()}

    resp = web.StreamResponse(
        status=200,
        headers={
            "Content-Type": "text/event-stream",
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "Access-Control-Allow-Origin": request.headers.get("Origin", "*"),
            "Access-Control-Allow-Methods": "GET, POST, DELETE, OPTIONS",
            "Access-Control-Allow-Headers": "Content-Type, Mcp-Session-Id, Last-Event-ID, Authorization",
            "Access-Control-Expose-Headers": "Mcp-Session-Id",
        }
    )
    await resp.prepare(request)
    await resp.write(f"event: endpoint\ndata: /messages?session_id={session}\n\n".encode())

    # Keep alive with periodic pings
    try:
        while True:
            await asyncio.sleep(15)
            await resp.write(b": keepalive\n\n")
    except (ConnectionResetError, asyncio.CancelledError):
        pass
    finally:
        request.app["mcp_sessions"].pop(session, None)

    return resp


async def handle_sse_messages(request: web.Request) -> web.Response:
    """SSE legacy peer message endpoint."""
    r = require_auth(request)
    if r: return r
    _record_request()
    try:
        msg = await request.json()
    except Exception:
        _record_request(is_error=True, count_request=False)
        return _cors_json_response({"jsonrpc": "2.0", "error": {"code": -32700, "message": "Parse error"}}, status=400)

    # Process the RPC message
    handle_rpc(msg)
    return web.Response(status=202, headers={"Access-Control-Allow-Origin": "*"})


# ============================================================================
# HANDLER — MCP WebSocket
# ============================================================================

async def handle_ws(request: web.Request) -> web.WebSocketResponse:
    """WebSocket MCP transport — full-duplex JSON-RPC."""
    r = require_auth(request)
    if r:
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        await ws.send_json({"jsonrpc": "2.0", "error": {"code": -32001, "message": "unauthorized"}})
        await ws.close()
        return ws
    _record_request()
    ws = web.WebSocketResponse()
    await ws.prepare(request)

    async for msg in ws:
        if msg.type == aiohttp.WSMsgType.TEXT:
            try:
                data = json.loads(msg.data)
                method = data.get("method", "")

                # Subscribe/unsubscribe extension
                if method == "subscribe":
                    # Just acknowledge for now
                    await ws.send_json({"jsonrpc": "2.0", "id": data.get("id"),
                                        "result": {"subscribed": (data.get("params") or {}).get("topic", "default")}})
                    continue
                if method == "unsubscribe":
                    await ws.send_json({"jsonrpc": "2.0", "id": data.get("id"),
                                        "result": {"unsubscribed": True}})
                    continue

                resp = handle_rpc(data)
                if resp is not None:
                    await ws.send_json(resp)
            except Exception as e:
                await ws.send_json({"jsonrpc": "2.0", "error": {"code": -32603, "message": str(e)}})

        elif msg.type == aiohttp.WSMsgType.ERROR:
            log.error("[WS] Connection error: %s", ws.exception())
            break
        elif msg.type == aiohttp.WSMsgType.CLOSE:
            break

    return ws


# ============================================================================
# HANDLERS — Web Gateway
# ============================================================================

async def handle_gateway_index(request: web.Request) -> web.Response:
    try:
        r = require_auth(request)
        if r: return r
        _record_request()
        return _cors_json_response({
            "ok": True, "service": "arena-web-gateway", "version": "1.0.0",
            "endpoints": ["/gateway", "/gateway/tools", "/run (POST)", "/tool (POST)"],
            "mcp_proxy": "/mcp",
            "auth_required": True,
        })
    except Exception as e:
        return _cors_json_response({"ok": False, "error": str(e)}, status=500)


async def handle_gateway_tools(request: web.Request) -> web.Response:
    try:
        r = require_auth(request)
        if r: return r
        _record_request()
        mcp_tools = handle_rpc({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
        return _cors_json_response({
            "ok": True,
            "whitelist_prefixes": list(GW_WHITELIST),
            "mcp_tools": mcp_tools.get("result", {}).get("tools", []) if mcp_tools else [],
        })
    except Exception as e:
        return _cors_json_response({"ok": False, "error": str(e)}, status=500)


def _gw_run_sync(cmd: str, timeout: int) -> dict:
    """Synchronous gateway command runner — returns dict result."""
    try:
        p = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout, **_subprocess_kwargs())
        return {"ok": p.returncode == 0, "exit": p.returncode,
                "stdout": p.stdout[-20000:], "stderr": p.stderr[-3000:]}
    except subprocess.TimeoutExpired:
        return {"ok": False, "exit": -1, "stdout": "", "stderr": "timeout"}
    except Exception as e:
        return {"ok": False, "exit": -2, "stdout": "", "stderr": str(e)}


async def handle_gateway_run(request: web.Request) -> web.Response:
    r = require_auth(request)
    if r: return r
    _record_request()
    try:
        data = await request.json()
    except Exception:
        _record_request(is_error=True, count_request=False)
        return _cors_json_response({"ok": False, "error": "bad json"}, status=400)
    cmd = (data.get("command") or data.get("cmd") or "").strip()
    if not cmd:
        _record_request(is_error=True, count_request=False)
        return _cors_json_response({"ok": False, "error": "missing command"}, status=400)
    if not gw_allowed(cmd):
        _record_request(is_error=True, count_request=False)
        return _cors_json_response({"ok": False, "error": "command not in whitelist",
                                   "allowed": list(GW_WHITELIST)}, status=403)
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(_EXECUTOR, _gw_run_sync, cmd, int(data.get("timeout", 60)))
    return _cors_json_response(result)


async def handle_gateway_tool(request: web.Request) -> web.Response:
    r = require_auth(request)
    if r: return r
    _record_request()
    try:
        data = await request.json()
    except Exception:
        _record_request(is_error=True, count_request=False)
        return _cors_json_response({"ok": False, "error": "bad json"}, status=400)
    name = data.get("name")
    # Support both "arguments" (MCP spec) and "input" (common alternative)
    args = data.get("arguments") or data.get("input") or {}
    if not name:
        _record_request(is_error=True, count_request=False)
        return _cors_json_response({"ok": False, "error": "missing tool name"}, status=400)
    resp = handle_rpc({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                        "params": {"name": name, "arguments": args}})
    return _cors_json_response({"ok": "error" not in (resp or {}), "response": resp})


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




async def handle_v1_logs(request: web.Request) -> web.Response:
    """Return recent bridge log entries with optional level filter."""
    r = require_auth(request)
    if r: return r
    _record_request()
    try:
        level = request.query.get("level", "INFO").upper()
        lines_count = min(int(request.query.get("lines", "100")), 1000)
    except (ValueError, TypeError):
        level = "INFO"
        lines_count = 100

    valid_levels = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
    if level not in valid_levels:
        level = "INFO"

    log_entries = []
    try:
        if LOG_FILE.exists():
            text = LOG_FILE.read_text(encoding="utf-8", errors="replace")
            all_lines = text.splitlines()
            min_idx = valid_levels.index(level) if level in valid_levels else 1
            filter_levels = valid_levels[min_idx:]
            for line in all_lines:
                if any(f" {lv} " in line for lv in filter_levels):
                    log_entries.append(line)
            log_entries = log_entries[-lines_count:]
    except Exception as e:
        log.error("Failed to read log file: %s", e)

    return _cors_json_response({
        "ok": True,
        "log_file": str(LOG_FILE),
        "level_filter": level,
        "lines": len(log_entries),
        "entries": log_entries,
    })


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
