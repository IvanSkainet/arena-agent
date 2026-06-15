"""CDP test-ws diagnostic probe implementation."""
from __future__ import annotations

import asyncio
import json
import time
import urllib.request

import aiohttp

from arena.handler_context import CdpDiagnosticHandlerContext


async def run_cdp_test_ws_probe(ctx: CdpDiagnosticHandlerContext, cdp, port: int) -> dict:
    result = {
        "ok": False,
        "port": port,
        "ws_connect_ok": False,
        "tab_ws_connect_ok": False,
        "ws_connect_time_s": None,
        "tab_ws_connect_time_s": None,
        "websockets_browser_ok": False,
        "websockets_tab_ok": False,
    }

    browser_proc = None

    try:
        loop = asyncio.get_event_loop()
        ctx.log_info("[test-ws] START port=%d", port)

        # Step 0: Launch Chromium on the test port
        try:
            await loop.run_in_executor(None, cdp._kill_port_processes, port)
            await asyncio.sleep(0.3)
        except Exception as e:
            ctx.log_warning("[test-ws] Kill stale processes failed: %s", e)

        browser_proc = await loop.run_in_executor(
            None, cdp.launch_browser, port, True
        )
        result["browser_pid"] = browser_proc.pid
        ctx.log_info("[test-ws] Browser launched pid=%d", browser_proc.pid)

        # Wait for port to become ready (max 10s)
        port_ready = False
        for attempt in range(20):
            await asyncio.sleep(0.5)
            if browser_proc.poll() is not None:
                result["browser_died"] = True
                result["browser_rc"] = browser_proc.returncode
                launch_diag = getattr(browser_proc, '_cdp_launch_diag', {})
                stderr_log = launch_diag.get("stderr_log", "")
                if stderr_log:
                    try:
                        with open(stderr_log, "r") as f:
                            result["browser_stderr"] = f.read().strip()[:1000]
                    except Exception:
                        pass
                result["error"] = f"Browser died (rc={browser_proc.returncode})"
                return ctx.cors_json_response(result)
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
            browser_proc = None
            return ctx.cors_json_response(result)

        # Step 1: Fetch /json/version
        raw_version = {}
        browser_ws_url = ""
        try:
            def _get_version():
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/version", timeout=5) as r:
                    return json.loads(r.read().decode())
            raw_version = await loop.run_in_executor(None, _get_version)
            browser_ws_url = raw_version.get("webSocketDebuggerUrl", "")
            result["raw_version_keys"] = list(raw_version.keys())
            # Chromium /json/version doesn't include "id" — extract from WS URL
            version_id = raw_version.get("id", "")
            if not version_id and browser_ws_url:
                import re as _re
                m = _re.search(r'/devtools/browser/([^/]+)', browser_ws_url)
                if m:
                    version_id = m.group(1)
            result["version_info"] = {
                "Browser": raw_version.get("Browser", "?")[:50],
                "webSocketDebuggerUrl": (browser_ws_url or "MISSING")[:80],
                "id": version_id or "N/A",
            }
            result["http_endpoint_ok"] = True
            ctx.log_info("[test-ws] /json/version: keys=%s wsUrl=%s id=%s",
                        list(raw_version.keys()),
                        raw_version.get("webSocketDebuggerUrl", "MISSING")[:60],
                        raw_version.get("id", "MISSING")[:30])
        except Exception as e:
            result["raw_version_error"] = f"{type(e).__name__}: {e}"
            result["http_endpoint_ok"] = False
            ctx.log_warning("[test-ws] /json/version FAILED: %s", e)

        # Step 2: Fetch /json/list
        raw_tabs = []
        tab_ws_url = ""
        tab_target_id = ""
        try:
            def _get_tabs():
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/list", timeout=5) as r:
                    return json.loads(r.read().decode())
            raw_tabs = await loop.run_in_executor(None, _get_tabs)
            page_tabs = [t for t in raw_tabs if t.get("type") == "page"]
            result["tab_count"] = len(raw_tabs)
            result["page_tab_count"] = len(page_tabs)
            if page_tabs:
                tab_ws_url = page_tabs[0].get("webSocketDebuggerUrl", "")
                tab_target_id = page_tabs[0].get("id", "")
                result["tab_target_id"] = tab_target_id
                for i, t in enumerate(page_tabs[:3]):
                    ctx.log_info("[test-ws] page[%d]: id=%s wsUrl=%s url=%s",
                                i, t.get("id", "?")[:20],
                                t.get("webSocketDebuggerUrl", "MISSING")[:60],
                                t.get("url", "?")[:50])
            ctx.log_info("[test-ws] /json/list: %d entries, %d pages",
                        len(raw_tabs), len(page_tabs))
        except Exception as e:
            result["raw_tabs_error"] = f"{type(e).__name__}: {e}"
            ctx.log_warning("[test-ws] /json/list FAILED: %s", e)

        # Construct WS URLs if webSocketDebuggerUrl is missing
        if not browser_ws_url:
            browser_id = raw_version.get("id", "")
            if browser_id:
                browser_ws_url = f"ws://127.0.0.1:{port}/devtools/browser/{browser_id}"
                result["browser_ws_constructed"] = True
                ctx.log_info("[test-ws] Constructed browser WS URL: %s", browser_ws_url)

        if not tab_ws_url and tab_target_id:
            tab_ws_url = f"ws://127.0.0.1:{port}/devtools/page/{tab_target_id}"
            result["tab_ws_constructed"] = True
            ctx.log_info("[test-ws] Constructed tab WS URL: %s", tab_ws_url)

        result["ws_url"] = browser_ws_url or "NONE"
        result["tab_ws_url"] = tab_ws_url[:80] if tab_ws_url else "NONE"

        # Step 3: Test TAB-level WebSocket — websockets library FIRST (most reliable on Py3.14)
        if tab_ws_url:
            # Strategy A: websockets library
            try:
                import websockets
                result["websockets_available"] = True
                t0 = time.monotonic()
                try:
                    ws = await asyncio.wait_for(
                        websockets.connect(tab_ws_url, open_timeout=3, close_timeout=2),
                        timeout=5
                    )
                    elapsed = time.monotonic() - t0
                    result["tab_ws_connect_ok"] = True
                    result["tab_ws_connect_time_s"] = round(elapsed, 2)
                    result["websockets_tab_ok"] = True
                    result["websockets_tab_time_s"] = round(elapsed, 2)
                    # Try CDP command
                    try:
                        await ws.send(json.dumps({"id": 1, "method": "Runtime.evaluate",
                                                   "params": {"expression": "1+1"}}))
                        resp = await asyncio.wait_for(ws.recv(), timeout=3)
                        result["websockets_tab_cdp_ok"] = True
                        result["websockets_tab_cdp_preview"] = resp[:200]
                        result["tab_cdp_ok"] = True
                        result["tab_cdp_response"] = resp[:200]
                    except Exception as e:
                        result["websockets_tab_cdp_ok"] = False
                        result["websockets_tab_cdp_error"] = str(e)
                    await ws.close()
                    result["ok"] = True
                    ctx.log_info("[test-ws] TAB WS OK (websockets, %.2fs)", elapsed)
                except asyncio.TimeoutError:
                    elapsed = time.monotonic() - t0
                    result["websockets_tab_ok"] = False
                    result["websockets_tab_error"] = f"TIMEOUT after {elapsed:.1f}s"
                    result["websockets_tab_time_s"] = round(elapsed, 2)
                    result["tab_ws_connect_error"] = f"websockets TIMEOUT after {elapsed:.1f}s"
                    ctx.log_warning("[test-ws] TAB WS websockets TIMEOUT (%.1fs)", elapsed)
                except Exception as e:
                    result["websockets_tab_ok"] = False
                    result["websockets_tab_error"] = f"{type(e).__name__}: {e}"
                    result["websockets_tab_time_s"] = None
                    result["tab_ws_connect_error"] = f"websockets {type(e).__name__}: {e}"
                    ctx.log_warning("[test-ws] TAB WS websockets FAILED: %s", e)
            except ImportError:
                result["websockets_available"] = False
                result["tab_ws_connect_error"] = "websockets library not available"

            # Strategy B: aiohttp (if websockets failed)
            if not result["tab_ws_connect_ok"]:
                try:
                    t0 = time.monotonic()
                    ws_timeout = aiohttp.ClientTimeout(total=3, connect=2, sock_connect=2)
                    connector = aiohttp.TCPConnector(force_close=True, enable_cleanup_closed=True)
                    async with aiohttp.ClientSession(timeout=ws_timeout, connector=connector) as session:
                        tab_ws = await asyncio.wait_for(
                            session.ws_connect(tab_ws_url, heartbeat=None, proxy=None),
                            timeout=5
                        )
                        elapsed = time.monotonic() - t0
                        result["tab_ws_connect_ok"] = True
                        result["tab_ws_connect_time_s"] = round(elapsed, 2)
                        # Try CDP command
                        try:
                            await tab_ws.send_json({"id": 1, "method": "Runtime.evaluate",
                                                     "params": {"expression": "1+1"}})
                            msg = await asyncio.wait_for(tab_ws.receive(), timeout=3)
                            if msg.type == aiohttp.WSMsgType.TEXT:
                                result["tab_cdp_ok"] = True
                                result["tab_cdp_response"] = msg.data[:200]
                        except Exception as e:
                            result["tab_cdp_ok"] = False
                            result["tab_cdp_error"] = str(e)
                        await tab_ws.close()
                        result["ok"] = True
                        ctx.log_info("[test-ws] TAB WS OK (aiohttp, %.2fs)", elapsed)
                except asyncio.TimeoutError:
                    elapsed = time.monotonic() - t0
                    result["tab_ws_connect_ok"] = False
                    result["tab_ws_connect_error"] = f"aiohttp TIMEOUT after {elapsed:.1f}s"
                    result["tab_ws_connect_time_s"] = round(elapsed, 2)
                    ctx.log_warning("[test-ws] TAB WS aiohttp TIMEOUT (%.1fs)", elapsed)
                except Exception as e:
                    result["tab_ws_connect_ok"] = False
                    result["tab_ws_connect_error"] = f"aiohttp {type(e).__name__}: {e}"
                    result["tab_ws_connect_time_s"] = None
                    ctx.log_warning("[test-ws] TAB WS aiohttp FAILED: %s", e)
        else:
            result["tab_ws_connect_ok"] = False
            result["tab_ws_connect_error"] = "No tab WS URL available"
            ctx.log_warning("[test-ws] No tab WS URL — cannot test tab WS")

        # Step 4: Test BROWSER-level WS (only if tab WS worked, or as extra info)
        if browser_ws_url:
            try:
                import websockets
                t0 = time.monotonic()
                try:
                    ws = await asyncio.wait_for(
                        websockets.connect(browser_ws_url, open_timeout=3, close_timeout=2),
                        timeout=5
                    )
                    elapsed = time.monotonic() - t0
                    result["ws_connect_ok"] = True
                    result["ws_connect_time_s"] = round(elapsed, 2)
                    result["websockets_browser_ok"] = True
                    result["websockets_browser_time_s"] = round(elapsed, 2)
                    try:
                        await ws.send(json.dumps({"id": 1, "method": "Target.getTargets"}))
                        resp = await asyncio.wait_for(ws.recv(), timeout=3)
                        result["websockets_cdp_ok"] = True
                        result["websockets_cdp_preview"] = resp[:200]
                    except Exception as e:
                        result["websockets_cdp_ok"] = False
                        result["websockets_cdp_error"] = str(e)
                    await ws.close()
                    if not result["ok"]:
                        result["ok"] = True
                    ctx.log_info("[test-ws] Browser WS OK (websockets, %.2fs)", elapsed)
                except (asyncio.TimeoutError, Exception) as e:
                    result["ws_connect_ok"] = False
                    result["ws_connect_error"] = f"websockets {type(e).__name__}: {e}"
                    ctx.log_warning("[test-ws] Browser WS FAILED: %s", e)
            except ImportError:
                result["ws_connect_ok"] = False
                result["ws_connect_error"] = "websockets library not available"
        else:
            result["ws_connect_ok"] = False
            result["ws_connect_error"] = "No browser WS URL available"

    except Exception as e:
        import traceback
        result["error"] = f"Unhandled: {type(e).__name__}: {e}"
        result["traceback"] = traceback.format_exc()
        ctx.log_error("[test-ws] UNHANDLED EXCEPTION: %s\n%s", e, traceback.format_exc())
    finally:
        # Always kill the test browser
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
