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

from arena.legacy_imports import *  # noqa: F401,F403,E402


_legacy_bridge_runtime = build_legacy_bridge_runtime(globals())
globals().update(_legacy_bridge_runtime)


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
