"""Compatibility exports for modular CDP browser process helpers."""
from __future__ import annotations

from arena.browser.cdp_client.process_discovery import (
    _build_chromium_cmd,
    _build_session_env,
    _resolve_browser_binary,
    find_browser_exe,
)
from arena.browser.cdp_client.process_helpers import _drain_stderr, _kill_port_processes, _ts, _write_diag_file
from arena.browser.cdp_client.process_launch import launch_browser

__all__ = [
    "find_browser_exe", "_resolve_browser_binary", "_build_session_env", "_build_chromium_cmd",
    "_ts", "_drain_stderr", "_kill_port_processes", "_write_diag_file", "launch_browser",
]
