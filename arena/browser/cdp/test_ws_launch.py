"""Launch/wait helpers for CDP test-ws diagnostics."""
from __future__ import annotations

import asyncio

from arena.handler_context import CdpDiagnosticHandlerContext


async def launch_test_browser(ctx: CdpDiagnosticHandlerContext, cdp, port: int, result: dict):
    """Kill stale listeners, launch Chromium and wait until the debug port is ready.

    Returns ``(browser_proc, done)`` where ``done`` means the caller should return
    the current result immediately.
    """
    loop = asyncio.get_running_loop()
    ctx.log_info("[test-ws] START port=%d", port)

    try:
        await loop.run_in_executor(None, cdp._kill_port_processes, port)
        await asyncio.sleep(0.3)
    except Exception as e:
        ctx.log_warning("[test-ws] Kill stale processes failed: %s", e)

    browser_proc = await loop.run_in_executor(None, cdp.launch_browser, port, True)
    result["browser_pid"] = browser_proc.pid
    ctx.log_info("[test-ws] Browser launched pid=%d", browser_proc.pid)

    port_ready = False
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
                        result["browser_stderr"] = f.read().strip()[:1000]
                except Exception:
                    pass
            result["error"] = f"Browser died (rc={browser_proc.returncode})"
            return browser_proc, True
        try:
            tabs = await loop.run_in_executor(None, cdp.list_tabs, port)
            if tabs:
                port_ready = True
                result["port_ready_after_s"] = (attempt + 1) * 0.5
                ctx.log_info("[test-ws] Port ready after %.1fs", (attempt + 1) * 0.5)
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
        return None, True

    return browser_proc, False
