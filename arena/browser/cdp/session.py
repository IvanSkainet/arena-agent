"""CDP session lifecycle handlers (connect/disconnect)."""
from __future__ import annotations

import asyncio
import json
import os
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone

from aiohttp import web

from arena.handler_context import CdpSessionHandlerContext


@dataclass(frozen=True)
class CdpSessionHandlers:
    connect: object
    disconnect: object


def make_cdp_session_handlers(ctx: CdpSessionHandlerContext) -> CdpSessionHandlers:
    async def handle_v1_cdp_connect(request):
        """POST /v1/browser/cdp/connect — Connect to browser CDP.
    
        Body (optional JSON):
            port: int (default: 9222)
            headless: bool (default: true)
        """
        r = ctx.require_auth(request)
        if r: return r
        ctx.record_request()
    
        cdp = ctx.get_cdp_module()
        if not cdp:
            ctx.record_request(is_error=True, count_request=False)
            return ctx.cors_json_response(
                {"ok": False, "error": "cdp_browser module not found. Install to scripts/ directory."},
                status=500
            )
    
        if ctx.cdp_state["connected"]:
            return ctx.cors_json_response({
                "ok": True,
                "message": "Already connected",
                "port": ctx.cdp_state["port"],
                "tab_count": ctx.cdp_state["manager"].tab_count if ctx.cdp_state["manager"] else 0,
            })
    
        if ctx.cdp_connect_lock.locked():
            return ctx.cors_json_response({"ok": False, "error": "CDP connect already in progress"}, status=409)
    
        # Parse optional body
        port = 9222
        headless = True
        try:
            body = await request.json()
            port = body.get("port", 9222)
            headless = body.get("headless", True)
        except Exception:
            pass
    
        async with ctx.cdp_connect_lock:
            try:
                mgr = cdp.CDPTabManager(port=port, headless=headless, auto_launch=True)

                # Read the diag file as a fallback — even if executor hangs, we may get partial info
                diag_file_path = os.path.join(tempfile.gettempdir(), f"cdp-browser-{os.getpid()}", "launch-diag.json")

                try:
                    await asyncio.wait_for(mgr.connect(), timeout=60)
                except asyncio.TimeoutError:
                    ctx.record_request(is_error=True, count_request=False)
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

                    return ctx.cors_json_response(
                        {"ok": False, "error": error_msg, "browser_crashed": browser_crashed,
                         "diagnostics": launch_diag, "stderr": (stderr_info or chromium_log)[:1500]},
                        status=408
                    )
            
                ctx.cdp_state["manager"] = mgr
                ctx.cdp_state["connected"] = True
                ctx.cdp_state["port"] = port
                ctx.cdp_state["headless"] = headless
                ctx.cdp_state["last_connect_time"] = datetime.now(timezone.utc).isoformat()
                ctx.cdp_state["last_disconnect_reason"] = None

                # Emit event (Phase 3)
                asyncio.create_task(ctx.emit_event("cdp_connect", {"port": port, "headless": headless}))

                # Start the health watcher for auto-reconnect
                ctx.start_cdp_watcher()
            
                # Verify active tab is actually connected (auto-connect may have failed silently)
                # v1.9.18: More aggressive retry with WS URL reconstruction
                active_tab = mgr.active_tab
                tab_connected = active_tab is not None and active_tab.connected
                if active_tab and not active_tab.connected:
                    # Retry 1: Try connect again (sometimes first attempt fails)
                    try:
                        await asyncio.wait_for(active_tab.connect(), timeout=25)
                        tab_connected = True
                        ctx.log_info("[CDP] Re-connected active tab %s on second attempt", mgr.active_tab_id)
                    except Exception as e:
                        ctx.log_warning("[CDP] Active tab auto-connect retry 1 failed: %s", e)
                
                    # Retry 2: Reconstruct WS URL from target_id and try again
                    if not tab_connected:
                        old_url = active_tab.ws_url
                        new_url = f"ws://127.0.0.1:{port}/devtools/page/{active_tab.target_id}"
                        if new_url != old_url:
                            ctx.log_info("[CDP] Retrying with constructed WS URL: %s (was: %s)", new_url, old_url[:60])
                            active_tab.ws_url = new_url
                            try:
                                await asyncio.wait_for(active_tab.connect(), timeout=15)
                                tab_connected = True
                                ctx.log_info("[CDP] Connected active tab with constructed WS URL")
                            except Exception as e:
                                ctx.log_warning("[CDP] Constructed WS URL retry failed: %s", e)
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
                return ctx.cors_json_response(result)
            except Exception as e:
                ctx.record_request(is_error=True, count_request=False)
                return ctx.cors_json_response(
                    {"ok": False, "error": f"Failed to connect: {str(e)}"},
                    status=500
                )


    async def handle_v1_cdp_disconnect(request):
        """POST /v1/browser/cdp/disconnect — Disconnect CDP session."""
        r = ctx.require_auth(request)
        if r: return r
        ctx.record_request()
    
        if not ctx.cdp_state["connected"]:
            return ctx.cors_json_response({"ok": True, "message": "Not connected"})
    
        if ctx.cdp_connect_lock.locked():
            return ctx.cors_json_response({"ok": False, "error": "CDP operation in progress"}, status=409)
    
        async with ctx.cdp_connect_lock:
            try:
                # Stop monitors/interceptors first
                if ctx.cdp_state.get("interceptor") and ctx.cdp_state["interceptor"].active:
                    await ctx.cdp_state["interceptor"].stop()
                if ctx.cdp_state.get("monitor") and ctx.cdp_state["monitor"].active:
                    await ctx.cdp_state["monitor"].stop()
                if ctx.cdp_state.get("cookie_mgr") and ctx.cdp_state["cookie_mgr"].active:
                    await ctx.cdp_state["cookie_mgr"].stop()
            
                # Stop the health watcher before disconnecting
                ctx.stop_cdp_watcher()

                # Close the manager
                if ctx.cdp_state["manager"]:
                    await ctx.cdp_state["manager"].close()
            
                ctx.cdp_state["manager"] = None
                ctx.cdp_state["monitor"] = None
                ctx.cdp_state["interceptor"] = None
                ctx.cdp_state["cookie_mgr"] = None
                ctx.cdp_state["connected"] = False
                ctx.cdp_state["last_disconnect_reason"] = "User disconnected"

                # Emit event (Phase 3)
                asyncio.create_task(ctx.emit_event("cdp_disconnect", {"reason": "User disconnected"}))

                return ctx.cors_json_response({"ok": True, "message": "CDP disconnected"})
            except Exception as e:
                ctx.record_request(is_error=True, count_request=False)
                return ctx.cors_json_response(
                    {"ok": False, "error": f"Disconnect error: {str(e)}"},
                    status=500
                )



    return CdpSessionHandlers(connect=handle_v1_cdp_connect, disconnect=handle_v1_cdp_disconnect)
