"""API v2 info/status/health/browser/deprecation handlers."""
from __future__ import annotations

import shutil
from pathlib import Path

from aiohttp import web

from arena.api_v2.common import auth_and_record, tls_ready
from arena.api_v2.constants import DEPRECATED_ENDPOINTS, MIGRATION_GUIDE, V2_ENDPOINTS
from arena.handler_context import ApiV2HandlerContext


def make_v2_index_handler(ctx: ApiV2HandlerContext):
    async def handle_v2_index(request: web.Request) -> web.Response:
        """GET /v2/ — API v2 index with versioning info and deprecation notices."""
        response = auth_and_record(ctx, request)
        if response:
            return response
        return ctx.cors_json_response({
            "ok": True,
            "api_version": "2",
            "bridge_version": ctx.version,
            "deprecations": DEPRECATED_ENDPOINTS,
            "v2_endpoints": V2_ENDPOINTS,
        })

    return handle_v2_index


def make_v2_status_handler(ctx: ApiV2HandlerContext):
    async def handle_v2_status(request: web.Request) -> web.Response:
        """GET /v2/status — Enhanced status with versioning info."""
        response = auth_and_record(ctx, request)
        if response:
            return response
        uptime = ctx.now() - ctx.metrics["start_time"]
        return ctx.cors_json_response({
            "ok": True,
            "version": ctx.version,
            "api_version": "2",
            "uptime_seconds": round(uptime, 1),
            "total_requests": ctx.metrics["total_requests"],
            "total_errors": ctx.metrics["total_errors"],
            "cdp": {
                "connected": ctx.cdp_state["connected"],
                "reconnects": ctx.cdp_state.get("reconnect_count", 0),
            },
            "watchdog": {
                "memory_mb": ctx.watchdog_state["memory_mb"],
                "cpu_percent": ctx.watchdog_state["cpu_percent"],
            },
            "cluster": {
                "role": ctx.cluster_state["role"],
                "enabled": ctx.cluster_config["enabled"],
            },
            "tls": {
                "enabled": ctx.tls_config["enabled"],
                "ready": tls_ready(ctx.tls_config),
            },
        })

    return handle_v2_status


def make_v2_health_handler(ctx: ApiV2HandlerContext):
    async def handle_v2_health(request: web.Request) -> web.Response:
        """GET /v2/health — Detailed health check with all subsystem status."""
        ctx.record_request()
        checks = {
            "bridge": True,
            "cdp": ctx.cdp_state["connected"],
            "watchdog": ctx.watchdog_state["last_check"] > 0,
            "tls": tls_ready(ctx.tls_config),
            "cluster": ctx.cluster_config["enabled"],
        }
        all_healthy = True
        return ctx.cors_json_response({
            "ok": all_healthy,
            "status": "healthy" if all_healthy else "degraded",
            "version": ctx.version,
            "api_version": "2",
            "checks": checks,
            "uptime_seconds": round(ctx.now() - ctx.metrics["start_time"], 1),
        })

    return handle_v2_health


def make_v2_browser_status_handler(ctx: ApiV2HandlerContext):
    async def handle_v2_browser_status(request: web.Request) -> web.Response:
        """GET /v2/browser/status — Combined CDP + browser status."""
        response = auth_and_record(ctx, request)
        if response:
            return response
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
            "browseract": {"available": bool(shutil.which("browser-act"))},
            "profiles": {"count": len(list(profiles_dir.glob("*.json"))) if profiles_dir.exists() else 0},
        })

    return handle_v2_browser_status


def make_v2_deprecations_handler(ctx: ApiV2HandlerContext):
    async def handle_v2_deprecations(request: web.Request) -> web.Response:
        """GET /v2/deprecations — List all deprecated v1 endpoints."""
        response = auth_and_record(ctx, request)
        if response:
            return response
        return ctx.cors_json_response({
            "ok": True,
            "api_version": "2",
            "deprecations": DEPRECATED_ENDPOINTS,
            "count": len(DEPRECATED_ENDPOINTS),
            "migration_guide": MIGRATION_GUIDE,
        })

    return handle_v2_deprecations
