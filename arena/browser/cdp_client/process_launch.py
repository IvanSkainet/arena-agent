"""Extracted module from scripts/cdp_browser.py."""
from __future__ import annotations

from arena.browser.cdp_client.common import *  # noqa: F401,F403

from arena.browser.cdp_client.process_discovery import _resolve_browser_binary, _build_session_env, _build_chromium_cmd
from arena.browser.cdp_client.process_helpers import _ts, _drain_stderr, _kill_port_processes, _write_diag_file

def launch_browser(port: int = DEFAULT_PORT, headless: bool = True) -> subprocess.Popen:
    """Launch a browser with remote debugging enabled. Returns the Popen object.

    This function MUST be fast — it starts Chromium and returns immediately.
    Port readiness is checked by the caller via list_tabs() retries.

    IMPORTANT: This function may be called from an executor thread.
    It must not hang — use short timeouts for all operations.
    NO time.sleep() calls — the caller handles all waiting.
    """
    import threading

    t0 = time.monotonic()
    logger.info("[CDP] launch_browser START port=%d headless=%s", port, headless)

    # Kill any stale processes on the debug port (fast, 3s timeout)
    try:
        killed = _kill_port_processes(port)
        if killed:
            logger.info("[CDP] Killed stale processes: %s", killed)
    except Exception as e:
        logger.warning("[CDP] Failed to kill stale processes: %s", e)

    exe = _resolve_browser_binary()
    logger.info("[CDP] Resolved browser binary: %s", exe)

    ud = os.path.join(tempfile.gettempdir(), f"cdp-browser-{os.getpid()}")
    # Clean stale lock files from previous runs — Chromium refuses to start
    # if SingletonLock or SingletonCookie exist from a previous instance.
    for lock_name in ["SingletonLock", "SingletonCookie", "SingletonSocket"]:
        lock_path = os.path.join(ud, lock_name)
        if os.path.exists(lock_path):
            try:
                os.unlink(lock_path)
                logger.info("[CDP] Cleaned stale %s", lock_name)
            except Exception:
                pass
    os.makedirs(ud, exist_ok=True)
    stderr_log_path = os.path.join(ud, "chromium-launch.log")

    cmd = _build_chromium_cmd(exe, port, headless, ud)
    session_env = _build_session_env()

    logger.info("[CDP] cmd=%s", " ".join(cmd[:6]))
    logger.info("[CDP] env: DBUS=%s XDG=%s DISPLAY=%s HOME=%s LDLP=%s",
                bool(session_env.get("DBUS_SESSION_BUS_ADDRESS")),
                bool(session_env.get("XDG_RUNTIME_DIR")),
                session_env.get("DISPLAY", ""),
                session_env.get("HOME", ""),
                bool(session_env.get("LD_LIBRARY_PATH")))

    launch_diag = {
        "exe": exe,
        "headless": headless,
        "port": port,
        "user_data_dir": ud,
        "cmd_full": " ".join(cmd),
        "env_has_dbus": bool(session_env.get("DBUS_SESSION_BUS_ADDRESS")),
        "env_has_xdg": bool(session_env.get("XDG_RUNTIME_DIR")),
        "env_has_display": bool(session_env.get("DISPLAY")),
        "env_has_home": bool(session_env.get("HOME")),
        "env_has_ld_library_path": bool(session_env.get("LD_LIBRARY_PATH")),
        "stderr_log": stderr_log_path,
        "start_time": _ts(),
    }

    # --- Direct launch ONLY — simplest, fastest approach ---
    # We use start_new_session=True so Chromium runs in its own session,
    # independent of the bridge process. The --ozone-platform=headless flag
    # ensures Chromium works without a display server. No sleep checks needed —
    # the caller (CDPTabManager.connect) handles port readiness via list_tabs() polling.
    logger.info("[CDP] Launching Chromium via direct Popen...")
    try:
        proc = subprocess.Popen(
            cmd,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            env=session_env,
            # Start in new session so Chromium doesn't get signals from bridge
            start_new_session=True,
        )
        # Drain stderr in background thread so the pipe doesn't fill up
        threading.Thread(target=_drain_stderr, args=(proc, stderr_log_path), daemon=True).start()

        elapsed = time.monotonic() - t0
        logger.info("[CDP] Chromium launched (pid=%d, %.1fs) — port readiness checked by caller",
                    proc.pid, elapsed)
        launch_diag["method"] = "direct"
        launch_diag["pid"] = proc.pid
        launch_diag["elapsed_s"] = round(elapsed, 1)
        proc._cdp_launch_diag = launch_diag
        _write_diag_file(launch_diag)
        return proc

    except Exception as e:
        elapsed = time.monotonic() - t0
        logger.error("[CDP] Direct launch EXCEPTION (%.1fs): %s", elapsed, e)
        launch_diag["direct_exception"] = str(e)
        launch_diag["all_failed"] = True
        launch_diag["total_elapsed_s"] = round(elapsed, 1)
        _write_diag_file(launch_diag)

        # Create a fake Popen that's already dead, with diagnostics attached
        try:
            proc = subprocess.Popen(["true"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            proc.wait(timeout=1)
        except Exception:
            proc = None

        if proc is not None:
            proc._cdp_launch_diag = launch_diag
        return proc
