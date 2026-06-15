"""Synchronous runner for CDP test-launch diagnostics."""
from __future__ import annotations

import os

from arena.browser.cdp.test_launch_common import (
    build_chromium_command,
    ensure_json_safe,
    headless_modes,
    user_data_dir,
)
from arena.browser.cdp.test_launch_process import run_launch_mode


def build_initial_result(*, exe: str, session_env: dict, port: int, headless: bool) -> dict:
    return {
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


def run_test_launch(cdp, *, port: int, headless: bool) -> dict:
    """Run Chromium and check CDP port while it is running."""
    try:
        exe = cdp._resolve_browser_binary()
    except Exception as e:
        return {"ok": False, "error": f"Cannot resolve browser binary: {e}"}

    if not os.path.isfile(exe):
        return {"ok": False, "error": f"Browser binary not found: {exe}"}

    try:
        cdp._kill_port_processes(port)
    except Exception:
        pass

    session_env = cdp._build_session_env()
    result = build_initial_result(exe=exe, session_env=session_env, port=port, headless=headless)

    for mode_name, headless_flags in headless_modes(headless):
        user_data = user_data_dir(mode_name)
        os.makedirs(user_data, exist_ok=True)
        cmd = build_chromium_command(exe, port=port, headless_flags=headless_flags, user_data=user_data)
        mode_result = run_launch_mode(
            cmd=cmd,
            env=session_env,
            port=port,
            mode_name=mode_name,
            user_data=user_data,
        )

        if mode_result.get("ok"):
            result["ok"] = True
            result["working_mode"] = mode_name
            result.update(mode_result)
            break
        result["modes_tried"] = result.get("modes_tried", []) + [mode_result]

    return ensure_json_safe(result)
