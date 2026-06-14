"""Lightweight CDP status and diagnostic handlers."""
from __future__ import annotations

import os
import shutil
import socket
import subprocess
import tempfile
from dataclasses import dataclass

from aiohttp import web

from arena.handler_context import CdpBasicHandlerContext


@dataclass(frozen=True)
class CdpBasicHandlers:
    status: object
    diag: object


def make_cdp_basic_handlers(ctx: CdpBasicHandlerContext) -> CdpBasicHandlers:
    async def handle_v1_cdp_status(request: web.Request) -> web.Response:
        """GET /v1/browser/cdp/status — CDP session status."""
        r = ctx.require_auth(request)
        if r:
            return r
        ctx.record_request()

        cdp = ctx.get_cdp_module()
        cdp_state = ctx.cdp_state
        mgr = cdp_state.get("manager")

        status = {
            "ok": True,
            "connected": cdp_state["connected"],
            "port": cdp_state["port"],
            "headless": cdp_state["headless"],
            "module_available": cdp is not None,
            "tab_count": mgr.tab_count if mgr else 0,
            "active_tab_id": mgr.active_tab_id if mgr else None,
            "network_monitoring": cdp_state.get("monitor") is not None and cdp_state["monitor"].active if cdp_state.get("monitor") else False,
            "interception_active": cdp_state.get("interceptor") is not None and cdp_state["interceptor"].active if cdp_state.get("interceptor") else False,
            "cookie_manager_active": cdp_state.get("cookie_mgr") is not None and cdp_state["cookie_mgr"].active if cdp_state.get("cookie_mgr") else False,
            "reconnect_count": cdp_state.get("reconnect_count", 0),
            "last_connect_time": cdp_state.get("last_connect_time"),
            "last_disconnect_reason": cdp_state.get("last_disconnect_reason"),
            "watcher_active": ctx.watcher_active(),
        }

        if mgr:
            status["tabs"] = [tab.to_dict() for tab in mgr.list_tabs()]

        return ctx.cors_json_response(status)

    async def handle_v1_cdp_diag(request: web.Request) -> web.Response:
        """GET /v1/browser/cdp/diag — Quick CDP diagnostics (no browser launch)."""
        r = ctx.require_auth(request)
        if r:
            return r
        ctx.record_request()

        uid = os.getuid() if hasattr(os, "getuid") else -1
        in_systemd = bool(os.environ.get("INVOCATION_ID") or os.environ.get("JOURNAL_STREAM"))

        diag = {
            "ok": True,
            "connected": ctx.cdp_state["connected"],
            "bridge_env": {
                "INVOCATION_ID": bool(os.environ.get("INVOCATION_ID")),
                "JOURNAL_STREAM": bool(os.environ.get("JOURNAL_STREAM")),
                "DBUS_SESSION_BUS_ADDRESS": os.environ.get("DBUS_SESSION_BUS_ADDRESS", ""),
                "XDG_RUNTIME_DIR": os.environ.get("XDG_RUNTIME_DIR", ""),
                "DISPLAY": os.environ.get("DISPLAY", ""),
                "WAYLAND_DISPLAY": os.environ.get("WAYLAND_DISPLAY", ""),
            },
            "bridge_env_ok": {
                "DBUS_SESSION_BUS_ADDRESS": bool(os.environ.get("DBUS_SESSION_BUS_ADDRESS")),
                "XDG_RUNTIME_DIR": bool(os.environ.get("XDG_RUNTIME_DIR")),
                "DISPLAY": bool(os.environ.get("DISPLAY")),
                "WAYLAND_DISPLAY": bool(os.environ.get("WAYLAND_DISPLAY")),
            },
            "systemd_run_available": bool(shutil.which("systemd-run")),
            "in_systemd": in_systemd,
        }

        cdp = ctx.get_cdp_module()
        if cdp:
            try:
                exe = cdp._resolve_browser_binary()
                diag["browser_binary"] = exe
                diag["browser_is_wrapper"] = False
                try:
                    with open(exe, "rb") as f:
                        first = f.read(4)
                    if first.startswith(b"#!"):
                        diag["browser_is_wrapper"] = True
                    elif first == b"\x7fELF":
                        diag["browser_is_elf"] = True
                except Exception:
                    pass
                try:
                    help_out = subprocess.run(
                        [exe, "--help"],
                        capture_output=True,
                        text=True,
                        timeout=5,
                        env={**os.environ, "LD_LIBRARY_PATH": os.environ.get("LD_LIBRARY_PATH", "")},
                    )
                    diag["ozone_support"] = "ozone" in (help_out.stdout + help_out.stderr).lower()
                except Exception:
                    diag["ozone_support"] = "unknown"
            except Exception as e:
                diag["browser_error"] = str(e)

            try:
                session_env = cdp._build_session_env()
                diag["session_env"] = {
                    "DBUS_SESSION_BUS_ADDRESS": session_env.get("DBUS_SESSION_BUS_ADDRESS", ""),
                    "XDG_RUNTIME_DIR": session_env.get("XDG_RUNTIME_DIR", ""),
                    "DISPLAY": session_env.get("DISPLAY", ""),
                    "WAYLAND_DISPLAY": session_env.get("WAYLAND_DISPLAY", ""),
                }
            except Exception as e:
                diag["session_env_error"] = str(e)

            try:
                exe = diag.get("browser_binary") or cdp._resolve_browser_binary()
                test_cmd = cdp._build_chromium_cmd(
                    exe,
                    9222,
                    True,
                    os.path.join(tempfile.gettempdir(), "cdp-browser-test"),
                )
                diag["headless_cmd"] = " ".join(test_cmd)
            except Exception:
                pass

        dbus_path = f"/run/user/{uid}/bus"
        diag["dbus_socket_exists"] = os.path.exists(dbus_path)
        diag["dbus_socket_path"] = dbus_path

        try:
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            sock.settimeout(2)
            sock.connect(dbus_path)
            sock.close()
            diag["dbus_socket_connectable"] = True
        except Exception as e:
            diag["dbus_socket_connectable"] = False
            diag["dbus_socket_error"] = str(e)

        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(1)
            result = sock.connect_ex(("127.0.0.1", 9222))
            sock.close()
            diag["port_9222_in_use"] = result == 0
        except Exception:
            diag["port_9222_in_use"] = "unknown"

        return ctx.cors_json_response(diag)

    return CdpBasicHandlers(status=handle_v1_cdp_status, diag=handle_v1_cdp_diag)
