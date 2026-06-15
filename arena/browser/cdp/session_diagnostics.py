"""Diagnostics helpers for CDP session connect failures."""
from __future__ import annotations

import json
import os
import tempfile


def launch_diag_file_path() -> str:
    return os.path.join(tempfile.gettempdir(), f"cdp-browser-{os.getpid()}", "launch-diag.json")


def chromium_stderr_log_path() -> str:
    return os.path.join(tempfile.gettempdir(), f"cdp-browser-{os.getpid()}", "chromium-launch.log")


def read_text_prefix(path: str, limit: int = 2000) -> str:
    try:
        with open(path, "r") as f:
            return f.read().strip()[:limit]
    except Exception:
        return ""


def read_json_file(path: str) -> dict:
    try:
        with open(path, "r") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def collect_connect_timeout_diagnostics(mgr) -> tuple[bool, dict, str]:
    """Collect launch diagnostics after CDP manager.connect() timeout."""
    browser_crashed = False
    launch_diag: dict = {}
    stderr_info = ""
    chromium_log = ""

    if getattr(mgr, "_browser_proc", None):
        if mgr._browser_proc.poll() is not None:
            browser_crashed = True
        launch_diag = getattr(mgr._browser_proc, "_cdp_launch_diag", {}) or {}
        stderr_log = launch_diag.get("stderr_log", "")
        if stderr_log:
            stderr_info = read_text_prefix(stderr_log)

    if not launch_diag:
        launch_diag = read_json_file(launch_diag_file_path())

    if not stderr_info:
        chromium_log = read_text_prefix(chromium_stderr_log_path())

    return browser_crashed, launch_diag, stderr_info or chromium_log


def build_connect_timeout_error(mgr, *, browser_crashed: bool, launch_diag: dict, stderr: str) -> str:
    """Build the historical human-readable CDP connect timeout message."""
    error_msg = "CDP connect timed out (60s)."
    if browser_crashed:
        error_msg += f" Browser exited (rc={mgr._browser_proc.returncode})."
    if stderr:
        error_msg += f" stderr: {stderr[:400]}"
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
        error_msg += (
            " | No diagnostics available (executor may have hung). Try manually: "
            "chromium --remote-debugging-port=9222 --headless=new --no-sandbox "
            "--ozone-platform=headless &"
        )
    return error_msg


def terminate_browser_proc(mgr) -> None:
    """Best-effort terminate/kill for a manager-owned browser process."""
    proc = getattr(mgr, "_browser_proc", None)
    if not proc or proc.poll() is not None:
        return
    try:
        proc.terminate()
        proc.wait(timeout=2)
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass
