"""CDP diagnostic raw info handler."""
from __future__ import annotations

import asyncio
import json
import os
import subprocess
import tempfile
import time
import urllib.request
from urllib.parse import parse_qs

import aiohttp
from aiohttp import web

from arena.handler_context import CdpDiagnosticHandlerContext


def make_cdp_raw_info_handler(ctx: CdpDiagnosticHandlerContext):
    async def handle_v1_cdp_raw_info(request):
        """GET /v1/browser/cdp/raw-info — Fetch raw /json/version and /json/list from a Chromium debug port.

        v1.9.19: New diagnostic endpoint to see EXACTLY what CachyOS Chromium returns
        from its CDP HTTP endpoints. This is critical for debugging WebSocket URL issues.

        Launches its own Chromium instance, waits for the port, fetches the raw HTTP
        responses, kills the browser, and returns the data. NO WebSocket testing here.

        Query params:
            port: int (default: 9223)
        """
        r = ctx.require_auth(request)
        if r: return r
        ctx.record_request()

        cdp = ctx.get_cdp_module()
        if not cdp:
            ctx.record_request(is_error=True)
            return ctx.cors_json_response(
                {"ok": False, "error": "cdp_browser module not found"},
                status=500
            )

        qs = parse_qs(request.query_string)
        port = int(qs.get("port", ["9223"])[0])

        result = {
            "ok": False,
            "port": port,
            "raw_version": None,
            "raw_tabs": None,
            "error": None,
        }

        try:
            loop = asyncio.get_event_loop()

            # Kill stale processes and launch
            try:
                await loop.run_in_executor(None, cdp._kill_port_processes, port)
                await asyncio.sleep(0.3)
            except Exception as e:
                ctx.log_warning("[raw-info] Kill stale processes failed: %s", e)

            browser_proc = await loop.run_in_executor(
                None, cdp.launch_browser, port, True
            )
            result["browser_pid"] = browser_proc.pid

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
                                result["browser_stderr"] = f.read().strip()[:2000]
                        except Exception:
                            pass
                    result["error"] = f"Browser died (rc={browser_proc.returncode})"
                    return ctx.cors_json_response(result)
                try:
                    tabs = await loop.run_in_executor(None, cdp.list_tabs, port)
                    if tabs:
                        port_ready = True
                        result["port_ready_after_s"] = (attempt + 1) * 0.5
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
                return ctx.cors_json_response(result)

            # Fetch /json/version — raw HTTP response
            try:
                def _get_version():
                    with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/version", timeout=5) as r:
                        raw = r.read().decode()
                        return json.loads(raw), raw
                version_data, version_raw = await loop.run_in_executor(None, _get_version)
                result["raw_version"] = version_data
                result["raw_version_keys"] = list(version_data.keys())
                result["has_webSocketDebuggerUrl"] = "webSocketDebuggerUrl" in version_data
                ws_url = version_data.get("webSocketDebuggerUrl", "")
                result["webSocketDebuggerUrl"] = ws_url or "MISSING"
                # Chromium /json/version doesn't include "id" field — extract from WS URL
                version_id = version_data.get("id", "")
                if not version_id and ws_url:
                    # ws://127.0.0.1:PORT/devtools/browser/<uuid>
                    import re
                    m = re.search(r'/devtools/browser/([^/]+)', ws_url)
                    if m:
                        version_id = m.group(1)
                result["version_id"] = version_id or "N/A"
                result["version_browser"] = version_data.get("Browser", "?")
                ctx.log_info("[raw-info] /json/version keys: %s", list(version_data.keys()))
                ctx.log_info("[raw-info] webSocketDebuggerUrl: %s", ws_url or "MISSING")
                ctx.log_info("[raw-info] id: %s", version_id or "N/A")
            except Exception as e:
                result["raw_version_error"] = f"{type(e).__name__}: {e}"
                ctx.log_warning("[raw-info] /json/version fetch failed: %s", e)

            # Fetch /json/list — raw HTTP response
            page_tabs = []  # Initialize BEFORE try to avoid UnboundLocalError if fetch fails
            try:
                def _get_tabs():
                    with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/list", timeout=5) as r:
                        raw = r.read().decode()
                        return json.loads(raw), raw
                tabs_data, tabs_raw = await loop.run_in_executor(None, _get_tabs)
                result["raw_tabs"] = tabs_data
                result["tab_count"] = len(tabs_data)
                # Summarize tab types and WS URLs
                page_tabs = [t for t in tabs_data if t.get("type") == "page"]
                result["page_tab_count"] = len(page_tabs)
                result["tab_ws_urls"] = [
                    {"id": t.get("id", "?"), "type": t.get("type", "?"),
                     "webSocketDebuggerUrl": t.get("webSocketDebuggerUrl", "MISSING"),
                     "url": t.get("url", "?")[:80]}
                    for t in tabs_data[:5]  # First 5 only
                ]
                ctx.log_info("[raw-info] /json/list: %d entries, %d pages", len(tabs_data), len(page_tabs))
                for i, t in enumerate(page_tabs[:3]):
                    ctx.log_info("[raw-info]   page[%d]: id=%s wsUrl=%s url=%s",
                             i, t.get("id", "?")[:20],
                             t.get("webSocketDebuggerUrl", "MISSING")[:60],
                             t.get("url", "?")[:50])
            except Exception as e:
                result["raw_tabs_error"] = f"{type(e).__name__}: {e}"
                ctx.log_warning("[raw-info] /json/list fetch failed: %s", e)

            # Quick WS probe using websockets library (if available)
            if page_tabs:
                tab_id = page_tabs[0].get("id", "")
                tab_ws_url = page_tabs[0].get("webSocketDebuggerUrl", "")
                if not tab_ws_url and tab_id:
                    tab_ws_url = f"ws://127.0.0.1:{port}/devtools/page/{tab_id}"
                    result["tab_ws_url_constructed"] = True
                result["tab_ws_url_tested"] = tab_ws_url

                if tab_ws_url:
                    # Try websockets library
                    try:
                        import websockets
                        t0 = time.monotonic()
                        ws = await asyncio.wait_for(
                            websockets.connect(tab_ws_url, open_timeout=3, close_timeout=2),
                            timeout=5
                        )
                        elapsed = time.monotonic() - t0
                        result["tab_ws_ok"] = True
                        result["tab_ws_time_s"] = round(elapsed, 2)
                        result["tab_ws_lib"] = "websockets"
                        # Try a CDP command
                        try:
                            await ws.send(json.dumps({"id": 1, "method": "Runtime.evaluate",
                                                       "params": {"expression": "1+1"}}))
                            resp = await asyncio.wait_for(ws.recv(), timeout=3)
                            result["tab_ws_cdp_ok"] = True
                            result["tab_ws_cdp_preview"] = resp[:200]
                        except Exception as e:
                            result["tab_ws_cdp_ok"] = False
                            result["tab_ws_cdp_error"] = str(e)
                        await ws.close()
                        result["ok"] = True
                    except ImportError:
                        result["tab_ws_ok"] = False
                        result["tab_ws_error"] = "websockets library not available"
                    except asyncio.TimeoutError:
                        result["tab_ws_ok"] = False
                        result["tab_ws_error"] = f"websockets TIMEOUT (5s) to {tab_ws_url}"
                    except Exception as e:
                        result["tab_ws_ok"] = False
                        result["tab_ws_error"] = f"{type(e).__name__}: {e} to {tab_ws_url}"

                    # If websockets failed, try aiohttp
                    if not result.get("tab_ws_ok"):
                        try:
                            import aiohttp as _aiohttp
                            t0 = time.monotonic()
                            ws_timeout = _aiohttp.ClientTimeout(total=3, connect=2, sock_connect=2)
                            connector = _aiohttp.TCPConnector(force_close=True)
                            async with _aiohttp.ClientSession(timeout=ws_timeout, connector=connector) as session:
                                tab_ws = await asyncio.wait_for(
                                    session.ws_connect(tab_ws_url, heartbeat=None, proxy=None),
                                    timeout=5
                                )
                                elapsed = time.monotonic() - t0
                                result["tab_ws_ok"] = True
                                result["tab_ws_time_s"] = round(elapsed, 2)
                                result["tab_ws_lib"] = "aiohttp"
                                try:
                                    await tab_ws.send_json({"id": 1, "method": "Runtime.evaluate",
                                                             "params": {"expression": "1+1"}})
                                    msg = await asyncio.wait_for(tab_ws.receive(), timeout=3)
                                    if msg.type == _aiohttp.WSMsgType.TEXT:
                                        result["tab_ws_cdp_ok"] = True
                                        result["tab_ws_cdp_preview"] = msg.data[:200]
                                except Exception as e:
                                    result["tab_ws_cdp_ok"] = False
                                    result["tab_ws_cdp_error"] = str(e)
                                await tab_ws.close()
                                result["ok"] = True
                        except asyncio.TimeoutError:
                            result["tab_ws_aiohttp_error"] = f"aiohttp TIMEOUT (5s) to {tab_ws_url}"
                        except Exception as e:
                            result["tab_ws_aiohttp_error"] = f"aiohttp {type(e).__name__}: {e} to {tab_ws_url}"

            if not result.get("ok"):
                # HTTP works but WS doesn't — still useful diagnostic
                result["ok"] = bool(result.get("raw_version") or result.get("raw_tabs"))

        except Exception as e:
            import traceback
            result["error"] = f"Unhandled: {type(e).__name__}: {e}"
            result["traceback"] = traceback.format_exc()
            ctx.log_error("[raw-info] UNHANDLED: %s\n%s", e, traceback.format_exc())
        finally:
            # Always kill the test browser
            if "browser_proc" in dir() and browser_proc:
                try:
                    browser_proc.terminate()
                    browser_proc.wait(timeout=3)
                except Exception:
                    try:
                        browser_proc.kill()
                    except Exception:
                        pass

        return ctx.cors_json_response(result)



    return handle_v1_cdp_raw_info
