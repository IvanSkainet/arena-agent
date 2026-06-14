"""CDP diagnostic handlers for launch/raw HTTP/WebSocket probes."""
from __future__ import annotations

import asyncio
import json
import os
import subprocess
import tempfile
import time
import urllib.request
from dataclasses import dataclass
from urllib.parse import parse_qs

import aiohttp
from aiohttp import web

from arena.handler_context import CdpDiagnosticHandlerContext


@dataclass(frozen=True)
class CdpDiagnosticHandlers:
    raw_info: object
    test_launch: object
    test_ws: object


def make_cdp_diagnostic_handlers(ctx: CdpDiagnosticHandlerContext) -> CdpDiagnosticHandlers:
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


    async def handle_v1_cdp_test_launch(request):
        """GET /v1/browser/cdp/test-launch — Diagnostic: try launching Chromium and capture output.

        This endpoint runs Chromium with Popen, checks port availability WHILE running,
        and tries multiple headless modes. It does NOT go through the CDPTabManager.

        Query params:
            port: int (default: 9223)
            headless: bool (default: true)
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
        headless = qs.get("headless", ["true"])[0].lower() != "false"

        loop = asyncio.get_event_loop()

        def _test_launch():
            """Run Chromium and check port while running. Returns result dict."""
            import socket as _socket
            import threading

            try:
                exe = cdp._resolve_browser_binary()
            except Exception as e:
                return {"ok": False, "error": f"Cannot resolve browser binary: {e}"}

            if not os.path.isfile(exe):
                return {"ok": False, "error": f"Browser binary not found: {exe}"}

            # Kill any stale processes on the test port
            try:
                cdp._kill_port_processes(port)
            except Exception:
                pass

            session_env = cdp._build_session_env()

            result = {
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

            # Try multiple headless modes — first --headless=new, then --headless (old)
            headless_modes = []
            if headless:
                headless_modes = [
                    ("headless=new + ozone=headless", ["--headless=new", "--ozone-platform=headless"]),
                    ("headless=new only", ["--headless=new"]),
                    ("headless (old mode)", ["--headless"]),
                ]
            else:
                headless_modes = [("headed", [])]

            for mode_name, headless_flags in headless_modes:
                ud = os.path.join(tempfile.gettempdir(), f"cdp-test-{os.getpid()}-{mode_name.replace(' ','_')[:20]}")
                os.makedirs(ud, exist_ok=True)

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
                    f"--user-data-dir={ud}",
                ])

                mode_result = {
                    "mode": mode_name,
                    "cmd": " ".join(cmd),
                    "user_data_dir": ud,
                }

                try:
                    # Use Popen so we can check port WHILE Chromium is running
                    proc = subprocess.Popen(
                        cmd,
                        stdin=subprocess.DEVNULL,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        env=session_env,
                        start_new_session=True,
                    )

                    # Drain stderr in background thread
                    stderr_lines = []
                    def _drain():
                        try:
                            for line in proc.stderr:
                                stderr_lines.append(line.decode(errors="replace") if isinstance(line, bytes) else line)
                        except Exception:
                            pass
                    threading.Thread(target=_drain, daemon=True).start()

                    # Wait up to 8 seconds, checking port every 0.5s
                    port_open = False
                    version_info = None
                    for attempt in range(16):  # 16 * 0.5s = 8s
                        time.sleep(0.5)
                        # Check if process died
                        if proc.poll() is not None:
                            mode_result["died_after_s"] = (attempt + 1) * 0.5
                            mode_result["returncode"] = proc.returncode
                            break
                        # Check if port is open
                        try:
                            s = _socket.socket(_socket.AF_INET, _socket.SOCK_STREAM)
                            s.settimeout(1)
                            if s.connect_ex(("127.0.0.1", port)) == 0:
                                port_open = True
                                s.close()
                                # Try to get version info
                                try:
                                    with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/version", timeout=3) as resp:
                                        version_info = json.loads(resp.read().decode())
                                except Exception as e:
                                    version_info = {"error": str(e)}
                                # Try to list tabs
                                try:
                                    with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/list", timeout=3) as resp:
                                        mode_result["tabs"] = json.loads(resp.read().decode())
                                except Exception:
                                    pass
                                break
                            s.close()
                        except Exception:
                            pass

                    mode_result["port_open"] = port_open
                    mode_result["pid"] = proc.pid
                    mode_result["still_running"] = proc.poll() is None

                    if port_open:
                        mode_result["ok"] = True
                        if version_info:
                            mode_result["version_info"] = version_info
                        # SUCCESS — kill the test process
                        try:
                            proc.terminate()
                            proc.wait(timeout=3)
                        except Exception:
                            try:
                                proc.kill()
                            except Exception:
                                pass
                        result["ok"] = True
                        result["working_mode"] = mode_name
                        result.update(mode_result)
                        break
                    else:
                        # Port didn't open — kill and try next mode
                        try:
                            proc.terminate()
                            proc.wait(timeout=3)
                        except Exception:
                            try:
                                proc.kill()
                            except Exception:
                                pass

                        mode_result["ok"] = False
                        mode_result["stderr_last10"] = [l.strip() for l in stderr_lines[-10:] if l.strip()]
                        result["modes_tried"] = result.get("modes_tried", []) + [mode_result]

                except Exception as e:
                    mode_result["ok"] = False
                    mode_result["error"] = f"{type(e).__name__}: {e}"
                    result["modes_tried"] = result.get("modes_tried", []) + [mode_result]

            # Safety: ensure no bytes values
            def _ensure_str(v):
                if isinstance(v, bytes):
                    return v.decode(errors="replace")
                if isinstance(v, dict):
                    return {k: _ensure_str(val) for k, val in v.items()}
                if isinstance(v, list):
                    return [_ensure_str(item) for item in v]
                return v
            result = _ensure_str(result)
            return result

        try:
            result = await loop.run_in_executor(ctx.executor, _test_launch)
            return ctx.cors_json_response(result)
        except Exception as e:
            ctx.record_request(is_error=True)
            return ctx.cors_json_response(
                {"ok": False, "error": f"Test launch failed: {str(e)}"},
                status=500
            )


    async def handle_v1_cdp_test_ws(request):
        """GET /v1/browser/cdp/test-ws — Diagnostic: test WebSocket connectivity to Chromium debug port.

        v1.9.19: Complete rewrite — ROBUST error handling, simplified flow.
        - Top-level try/except to ALWAYS return valid JSON (fixes all `?` values)
        - ONLY tests tab-level WS (most important, skip browser WS to save time)
        - websockets library FIRST, aiohttp as fallback
        - Total time capped at ~20s to fit within curl --max-time 45
        - Includes raw /json/version and /json/list responses for debugging

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
                {"ok": False, "error": "cdp_browser module not found",
                 "ws_connect_ok": False, "tab_ws_connect_ok": False},
                status=500
            )

        qs = parse_qs(request.query_string)
        port = int(qs.get("port", ["9223"])[0])

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

        return ctx.cors_json_response(result)



    return CdpDiagnosticHandlers(
        raw_info=handle_v1_cdp_raw_info,
        test_launch=handle_v1_cdp_test_launch,
        test_ws=handle_v1_cdp_test_ws,
    )
