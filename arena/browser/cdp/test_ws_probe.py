"""CDP test-ws diagnostic probe implementation."""
from __future__ import annotations

import traceback

from arena.browser.cdp.test_ws_http import fetch_ws_targets
from arena.browser.cdp.test_ws_launch import launch_test_browser
from arena.browser.cdp.test_ws_socket import probe_browser_ws, probe_tab_ws
from arena.handler_context import CdpDiagnosticHandlerContext


def _initial_result(port: int) -> dict:
    return {
        "ok": False,
        "port": port,
        "ws_connect_ok": False,
        "tab_ws_connect_ok": False,
        "ws_connect_time_s": None,
        "tab_ws_connect_time_s": None,
        "websockets_browser_ok": False,
        "websockets_tab_ok": False,
    }


async def run_cdp_test_ws_probe(ctx: CdpDiagnosticHandlerContext, cdp, port: int) -> dict:
    result = _initial_result(port)
    browser_proc = None

    try:
        browser_proc, done = await launch_test_browser(ctx, cdp, port, result)
        if done:
            return result

        browser_ws_url, tab_ws_url = await fetch_ws_targets(ctx, port, result)
        await probe_tab_ws(ctx, tab_ws_url, result)
        await probe_browser_ws(ctx, browser_ws_url, result)

    except Exception as e:
        result["error"] = f"Unhandled: {type(e).__name__}: {e}"
        result["traceback"] = traceback.format_exc()
        ctx.log_error("[test-ws] UNHANDLED EXCEPTION: %s\n%s", e, traceback.format_exc())
    finally:
        if browser_proc:
            try:
                browser_proc.terminate()
                browser_proc.wait(timeout=3)
            except Exception:
                try:
                    browser_proc.kill()
                except Exception:
                    pass

    return result
