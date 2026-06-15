"""CDP diagnostic test launch handler."""
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


def make_cdp_test_launch_handler(ctx: CdpDiagnosticHandlerContext):
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



    return handle_v1_cdp_test_launch
