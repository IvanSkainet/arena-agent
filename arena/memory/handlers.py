"""Handlers for memory and recall endpoints."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from urllib.parse import parse_qs

from aiohttp import web

from arena.handler_context import MemoryHandlerContext


@dataclass(frozen=True)
class MemoryHandlers:
    memory_get: object
    memory_set: object
    memory_delete: object
    recall: object
    recall_digest: object


def make_memory_handlers(ctx: MemoryHandlerContext) -> MemoryHandlers:
    async def handle_v1_memory(request: web.Request) -> web.Response:
        try:
            r = ctx.require_auth(request)
            if r:
                return r
            ctx.record_request()
            qs = parse_qs(request.query_string)
            q = qs.get("q", [""])[0]
            try:
                offset = max(0, int(qs.get("offset", ["0"])[0]))
                limit = min(500, max(1, int(qs.get("limit", ["100"])[0])))
            except (ValueError, TypeError):
                offset = 0
                limit = 100
            loop = asyncio.get_event_loop()
            total, facts = await loop.run_in_executor(ctx.executor, ctx.search_facts_paged, q, offset, limit)
            result = {"ok": True, "total": total, "count": len(facts), "facts": facts}
            if offset + limit < total:
                result["next_offset"] = offset + limit
            return ctx.cors_json_response(result)
        except Exception as e:
            return ctx.cors_json_response({"ok": False, "error": str(e)}, status=500)

    async def handle_v1_memory_set(request: web.Request) -> web.Response:
        r = ctx.require_auth(request)
        if r:
            return r
        ctx.record_request()
        try:
            data = await request.json()
        except Exception as e:
            ctx.record_request(is_error=True, count_request=False)
            return ctx.cors_json_response({"ok": False, "error": f"invalid json: {e}"}, status=400)
        key = str(data.get("key", "")).strip()
        value = str(data.get("value", "")).strip()
        if not key:
            ctx.record_request(is_error=True, count_request=False)
            return ctx.cors_json_response({"ok": False, "error": "missing key"}, status=400)
        entry = {"key": key, "value": value, "tags": data.get("tags") or [], "timestamp": ctx.utc_now()}
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(ctx.executor, ctx.write_fact, entry)
        return ctx.cors_json_response({"ok": True, "fact": entry})

    async def handle_v1_memory_delete(request: web.Request) -> web.Response:
        r = ctx.require_auth(request)
        if r:
            return r
        ctx.record_request()
        try:
            data = await request.json()
        except Exception as e:
            ctx.record_request(is_error=True, count_request=False)
            return ctx.cors_json_response({"ok": False, "error": f"invalid json: {e}"}, status=400)
        key = str(data.get("key", "")).strip()
        if not key:
            ctx.record_request(is_error=True, count_request=False)
            return ctx.cors_json_response({"ok": False, "error": "missing key"}, status=400)
        loop = asyncio.get_event_loop()
        deleted = await loop.run_in_executor(ctx.executor, ctx.delete_fact, key)
        if deleted:
            ctx.audit({"event": "memory_delete", "key": key})
            return ctx.cors_json_response({"ok": True, "deleted": key})
        return ctx.cors_json_response({"ok": False, "error": "key not found"}, status=404)

    async def handle_v1_recall(request: web.Request) -> web.Response:
        r = ctx.require_auth(request)
        if r:
            return r
        ctx.record_request()
        qs = parse_qs(request.query_string)
        query = qs.get("q", [""])[0]
        try:
            top = int(qs.get("top", ["5"])[0])
        except ValueError:
            top = 5
        if not query:
            ctx.record_request(is_error=True, count_request=False)
            return ctx.cors_json_response({"ok": False, "error": "missing q parameter"}, status=400)
        try:
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(ctx.executor, ctx.recall_sync, query, top)
            return ctx.cors_json_response(result)
        except Exception as e:
            ctx.record_request(is_error=True, count_request=False)
            return ctx.cors_json_response({"ok": False, "error": str(e)}, status=500)

    async def handle_v1_recall_digest(request: web.Request) -> web.Response:
        r = ctx.require_auth(request)
        if r:
            return r
        ctx.record_request()
        try:
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(ctx.executor, ctx.recall_digest_sync)
            return ctx.cors_json_response(result)
        except Exception as e:
            ctx.record_request(is_error=True, count_request=False)
            return ctx.cors_json_response({"ok": False, "error": str(e)}, status=500)

    return MemoryHandlers(
        memory_get=handle_v1_memory,
        memory_set=handle_v1_memory_set,
        memory_delete=handle_v1_memory_delete,
        recall=handle_v1_recall,
        recall_digest=handle_v1_recall_digest,
    )
