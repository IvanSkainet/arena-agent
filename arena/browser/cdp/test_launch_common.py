"""Common helpers for CDP test-launch diagnostics."""
from __future__ import annotations

import os
import tempfile
from typing import Any


def headless_modes(headless: bool) -> list[tuple[str, list[str]]]:
    """Return launch modes in the historical preference order."""
    if headless:
        return [
            ("headless=new + ozone=headless", ["--headless=new", "--ozone-platform=headless"]),
            ("headless=new only", ["--headless=new"]),
            ("headless (old mode)", ["--headless"]),
        ]
    return [("headed", [])]


def user_data_dir(mode_name: str) -> str:
    return os.path.join(tempfile.gettempdir(), f"cdp-test-{os.getpid()}-{mode_name.replace(' ', '_')[:20]}")


def build_chromium_command(exe: str, *, port: int, headless_flags: list[str], user_data: str) -> list[str]:
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
        f"--user-data-dir={user_data}",
    ])
    return cmd


def ensure_json_safe(value: Any):
    """Recursively convert bytes values returned from process helpers to strings."""
    if isinstance(value, bytes):
        return value.decode(errors="replace")
    if isinstance(value, dict):
        return {k: ensure_json_safe(v) for k, v in value.items()}
    if isinstance(value, list):
        return [ensure_json_safe(item) for item in value]
    return value
