"""Handlers for the v2 compatibility API endpoints."""
from __future__ import annotations

import asyncio
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from aiohttp import web

from arena.handler_context import ApiV2HandlerContext

DEPRECATED_ENDPOINTS: dict[str, dict[str, str]] = {
    "/v1/service/info": {"deprecated_since": "1.9.27", "replacement": "/v1/status", "removal_version": "2.3.0"},
    "/v1/sys/svc": {"deprecated_since": "1.9.27", "replacement": "/v1/status", "removal_version": "2.3.0"},
    "/v1/sys/funnel": {"deprecated_since": "1.9.27", "replacement": "/v1/tailscale/funnel/status", "removal_version": "2.3.0"},
}


@dataclass(frozen=True)
class V2Handlers:
    index: object
    status: object
    health: object
    browser_status: object
    exec: object
    deprecations: object


def cfg_get_max_timeout(request: web.Request) -> int:
    """Get max timeout from bridge config."""
    try:
        return request.app["cfg"].get("max_timeout", 600)
    except Exception:
        return 600


def _tls_ready(tls_config: dict[str, Any]) -> bool:
    cert_path = tls_config.get("cert_path")
    if not cert_path:
        return False
    return bool(tls_config.get("enabled") and Path(cert_path).exists())


def make_v2_handlers(ctx: ApiV2HandlerContext) -> V2Handlers:
    async def handle_v2_index(request: web.Request) -> web.Response:
        """GET /v2/ — API v2 index with versioning info and deprecation notices."""
        r = ctx.require_auth(request)
        if r:
            return r
        ctx.record_request()

        return ctx.cors_json_response({
            "ok": True,
            "api_version": "2",
            "bridge_version": ctx.version,
            "deprecations": DEPRECATED_ENDPOINTS,
            "v2_endpoints": {
                "GET /v2/": "API v2 index",
                "GET /v2/status": "Bridge status (replaces /v1/status)",
                "GET /v2/health": "Detailed health check",
                "GET /v2/browser/status": "CDP + browser status combined",
                "POST /v2/exec": "Exec with sandbox by default",
                "GET /v2/deprecations": "List deprecated v1 endpoints",
            }
        })

    async def handle_v2_status(request: web.Request) -> web.Response:
        """GET /v2/status — Enhanced status with versioning info."""
        r = ctx.require_auth(request)
        if r:
            return r
        ctx.record_request()

        uptime = ctx.now() - ctx.metrics["start_time"]

        return ctx.cors_json_response({
            "ok": True,
            "version": ctx.version,
            "api_version": "2",
            "uptime_seconds": round(uptime, 1),
            "total_requests": ctx.metrics["total_requests"],
            "total_errors": ctx.metrics["total_errors"],
            "cdp": {"connected": ctx.cdp_state["connected"],
                    "reconnects": ctx.cdp_state.get("reconnect_count", 0)},
            "watchdog": {"memory_mb": ctx.watchdog_state["memory_mb"],
                         "cpu_percent": ctx.watchdog_state["cpu_percent"]},
            "cluster": {"role": ctx.cluster_state["role"],
                        "enabled": ctx.cluster_config["enabled"]},
            "tls": {"enabled": ctx.tls_config["enabled"],
                    "ready": _tls_ready(ctx.tls_config)},
        })

    async def handle_v2_health(request: web.Request) -> web.Response:
        """GET /v2/health — Detailed health check with all subsystem status."""
        ctx.record_request()

        checks = {
            "bridge": True,
            "cdp": ctx.cdp_state["connected"],
            "watchdog": ctx.watchdog_state["last_check"] > 0,
            "tls": _tls_ready(ctx.tls_config),
            "cluster": ctx.cluster_config["enabled"],
        }

        all_healthy = True  # Bridge is always healthy if responding

        return ctx.cors_json_response({
            "ok": all_healthy,
            "status": "healthy" if all_healthy else "degraded",
            "version": ctx.version,
            "api_version": "2",
            "checks": checks,
            "uptime_seconds": round(ctx.now() - ctx.metrics["start_time"], 1),
        })

    async def handle_v2_browser_status(request: web.Request) -> web.Response:
        """GET /v2/browser/status — Combined CDP + browser status."""
        r = ctx.require_auth(request)
        if r:
            return r
        ctx.record_request()

        profiles_dir = Path(ctx.profiles_dir)
        return ctx.cors_json_response({
            "ok": True,
            "api_version": "2",
            "cdp": {
                "connected": ctx.cdp_state["connected"],
                "headless": ctx.cdp_state["headless"],
                "port": ctx.cdp_state["port"],
                "reconnect_count": ctx.cdp_state.get("reconnect_count", 0),
            },
            "browseract": {
                "available": bool(shutil.which("browser-act")),
            },
            "profiles": {
                "count": len(list(profiles_dir.glob("*.json"))) if profiles_dir.exists() else 0,
            }
        })

    async def handle_v2_exec(request: web.Request) -> web.Response:
        """POST /v2/exec — Execute command in sandbox by default.

        Same as /v1/exec but with sandbox enabled by default.
        Accepts all /v1/exec params plus:
          - sandbox: bool (default: True)
          - max_cpu_seconds: int (default: from sandbox config)
        """
        r = ctx.require_auth(request)
        if r:
            return r
        ctx.record_request()

        try:
            data = await request.json()
        except Exception as e:
            return ctx.cors_json_response({"ok": False, "error": f"invalid json: {e}"}, status=400)

        cmd = data.get("cmd", "")
        if not cmd:
            return ctx.cors_json_response({"ok": False, "error": "missing 'cmd'"}, status=400)

        block = ctx.blocked_reason(cmd)
        if block:
            return ctx.cors_json_response({"ok": False, "error": block}, status=403)

        use_sandbox = data.get("sandbox", True)

        if use_sandbox and ctx.sandbox_config["enabled"]:
            # Apply same command allowlist as /v1/sandbox
            first_cmd = ctx.first_word(cmd)
            allowed = ctx.sandbox_config["allowed_commands"]
            if allowed and first_cmd not in allowed:
                return ctx.cors_json_response({
                    "ok": False, "error": f"command '{first_cmd}' not in allowed list (sandbox mode)",
                    "allowed": allowed, "api_version": "2"
                }, status=403)
            timeout = min(int(data.get("timeout", 30)), ctx.sandbox_config["max_cpu_seconds"])
            result = await ctx.run_sandboxed(cmd, timeout=timeout)
            result["sandbox"] = True
            result["api_version"] = "2"
        else:
            # Fall back to normal exec
            timeout = min(int(data.get("timeout", 60)), ctx.cfg_get_max_timeout(request))
            try:
                proc = await asyncio.create_subprocess_shell(
                    cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
                result = {
                    "ok": proc.returncode == 0,
                    "exit_code": proc.returncode,
                    "stdout": ctx.decode_output(stdout)[-50000:],
                    "stderr": ctx.decode_output(stderr)[-10000:],
                    "sandbox": False,
                    "api_version": "2",
                }
            except asyncio.TimeoutError:
                result = {"ok": False, "error": f"timeout after {timeout}s", "sandbox": False, "api_version": "2"}
            except Exception as e:
                result = {"ok": False, "error": str(e), "sandbox": False, "api_version": "2"}

        ctx.audit({"type": "exec_v2", "cmd_len": len(cmd), "sandbox": use_sandbox,
                   "exit_code": result.get("exit_code")})
        await ctx.emit_event("exec", {"cmd": cmd[:50], "ok": result["ok"], "sandbox": use_sandbox})
        ctx.record_request(is_exec=True)

        return ctx.cors_json_response(result)

    async def handle_v2_deprecations(request: web.Request) -> web.Response:
        """GET /v2/deprecations — List all deprecated v1 endpoints."""
        r = ctx.require_auth(request)
        if r:
            return r
        ctx.record_request()

        return ctx.cors_json_response({
            "ok": True,
            "api_version": "2",
            "deprecations": DEPRECATED_ENDPOINTS,
            "count": len(DEPRECATED_ENDPOINTS),
            "migration_guide": {
                "/v1/service/info → /v1/status": "Use /v1/status for all service information",
                "/v1/sys/svc → /v1/status": "Service status is now part of /v1/status",
                "/v1/sys/funnel → /v1/tailscale/funnel/status": "Funnel status moved to tailscale namespace",
            }
        })

    return V2Handlers(
        index=handle_v2_index,
        status=handle_v2_status,
        health=handle_v2_health,
        browser_status=handle_v2_browser_status,
        exec=handle_v2_exec,
        deprecations=handle_v2_deprecations,
    )
