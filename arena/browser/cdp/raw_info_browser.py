"""Browser process lifecycle helpers for CDP raw-info diagnostics."""
from __future__ import annotations

import asyncio

from arena.handler_context import CdpDiagnosticHandlerContext


async def launch_raw_info_browser(ctx: CdpDiagnosticHandlerContext, cdp, port: int, result: dict):
    """Kill stale debug-port users, launch Chromium, and store PID in result."""
    loop = asyncio.get_event_loop()
    try:
        await loop.run_in_executor(None, cdp._kill_port_processes, port)
        await asyncio.sleep(0.3)
    except Exception as e:
        ctx.log_warning("[raw-info] Kill stale processes failed: %s", e)

    browser_proc = await loop.run_in_executor(None, cdp.launch_browser, port, True)
    result["browser_pid"] = browser_proc.pid
    return browser_proc


async def wait_for_raw_info_port(ctx: CdpDiagnosticHandlerContext, cdp, port: int, browser_proc, result: dict) -> bool:
    """Wait up to 10s for Chromium's CDP HTTP endpoint to list tabs."""
    loop = asyncio.get_event_loop()
    for attempt in range(20):
        await asyncio.sleep(0.5)
        if browser_proc.poll() is not None:
            result["browser_died"] = True
            result["browser_rc"] = browser_proc.returncode
            launch_diag = getattr(browser_proc, "_cdp_launch_diag", {})
            stderr_log = launch_diag.get("stderr_log", "")
            if stderr_log:
                try:
                    with open(stderr_log, "r") as f:
                        result["browser_stderr"] = f.read().strip()[:2000]
                except Exception:
                    pass
            result["error"] = f"Browser died (rc={browser_proc.returncode})"
            return False
        try:
            tabs = await loop.run_in_executor(None, cdp.list_tabs, port)
            if tabs:
                result["port_ready_after_s"] = (attempt + 1) * 0.5
                return True
        except Exception:
            pass

    result["error"] = f"Chromium port {port} not ready after 10s"
    return False


def stop_raw_info_browser(browser_proc) -> None:
    """Best-effort termination for the diagnostic Chromium process."""
    if not browser_proc:
        return
    try:
        browser_proc.terminate()
        browser_proc.wait(timeout=3)
    except Exception:
        try:
            browser_proc.kill()
        except Exception:
            pass
