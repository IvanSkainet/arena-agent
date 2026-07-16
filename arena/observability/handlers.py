"""Handlers for audit, request log, and webhooks."""
from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from urllib.parse import parse_qs

from aiohttp import web

from arena.handler_context import ObservabilityHandlerContext
from arena.handler_helpers import authed, err_json


@dataclass(frozen=True)
class ObservabilityHandlers:
    audit: object
    audit_stats: object
    audit_log: object
    webhooks_get: object
    webhooks_set: object


def make_observability_handlers(ctx: ObservabilityHandlerContext) -> ObservabilityHandlers:
    @authed(ctx)
    async def handle_v1_audit(request: web.Request) -> web.Response:
        qs = parse_qs(request.query_string)
        try:
            n = int(qs.get("lines", ["100"])[0])
        except ValueError:
            n = 100
        loop = asyncio.get_running_loop()
        lines = await loop.run_in_executor(ctx.executor, ctx.read_tail, ctx.audit_path, n)
        rows = []
        for line in lines:
            try:
                rows.append(json.loads(line))
            except Exception:
                rows.append({"raw": line})
        return ctx.cors_json_response({"ok": True, "lines": len(rows), "audit": str(ctx.audit_path), "events": rows})

    @authed(ctx)
    async def handle_v1_audit_stats(request: web.Request) -> web.Response:
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(ctx.executor, ctx.audit_stats_sync)
        return ctx.cors_json_response(result)

    @authed(ctx)
    async def handle_v1_audit_log(request: web.Request) -> web.Response:
        try:
            lines_count = min(int(request.query.get("lines", "100")), 1000)
            method_filter = request.query.get("method", "").upper()
            path_filter = request.query.get("path", "")
            status_filter = request.query.get("status", "")
        except (ValueError, TypeError):
            lines_count = 100
            method_filter = ""
            path_filter = ""
            status_filter = ""
        entries = ctx.read_request_log(
            ctx.request_log_file,
            lines_count=lines_count,
            method_filter=method_filter,
            path_filter=path_filter,
            status_filter=status_filter,
        )
        return ctx.cors_json_response({
            "ok": True,
            "log_file": str(ctx.request_log_file),
            "filters": {"method": method_filter, "path": path_filter, "status": status_filter, "lines": lines_count},
            "count": len(entries),
            "entries": entries,
        })

    @authed(ctx)
    async def handle_v1_webhooks_get(request: web.Request) -> web.Response:
        loop = asyncio.get_running_loop()
        data = await loop.run_in_executor(ctx.executor, ctx.load_webhooks)
        return ctx.cors_json_response({"ok": True, "webhooks": data})

    @authed(ctx)
    async def handle_v1_webhooks_set(request: web.Request) -> web.Response:
        try:
            data = await request.json()
        except Exception:
            return ctx.cors_json_response({"ok": False, "error": "invalid json"}, status=400)
        cfg, err = ctx.normalize_webhooks_config(data)
        if err:
            return ctx.cors_json_response({"ok": False, "error": err}, status=400)
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(ctx.executor, ctx.save_webhooks, cfg)
        ctx.audit({"type": "webhooks_updated", "urls_count": len(cfg["urls"])})
        return ctx.cors_json_response({"ok": True, "webhooks": cfg})

    return ObservabilityHandlers(
        audit=handle_v1_audit,
        audit_stats=handle_v1_audit_stats,
        audit_log=handle_v1_audit_log,
        webhooks_get=handle_v1_webhooks_get,
        webhooks_set=handle_v1_webhooks_set,
    )
