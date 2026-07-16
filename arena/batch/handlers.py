"""Handlers for batch operations."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass

import aiohttp
from aiohttp import web
from arena.app_keys import APP_CFG

from arena.handler_context import BatchHandlerContext
from arena.handler_helpers import authed, err_json


@dataclass(frozen=True)
class BatchHandlers:
    batch: object


def make_batch_handlers(ctx: BatchHandlerContext) -> BatchHandlers:
    @authed(ctx)
    async def handle_v1_batch(request: web.Request) -> web.Response:
        """POST /v1/batch — Execute multiple operations in parallel.

        Body: {"operations": [{"method": "GET", "path": "/v1/status"}, ...]}
        Optional: "max_concurrent": 5, "fail_fast": false
        """
        try:
            data = await request.json()
        except Exception as e:
            return ctx.cors_json_response({"ok": False, "error": f"invalid json: {e}"}, status=400)

        operations = data.get("operations", [])
        if not operations:
            return ctx.cors_json_response({"ok": False, "error": "operations array is required"}, status=400)
        if len(operations) > 20:
            return ctx.cors_json_response({"ok": False, "error": "maximum 20 operations per batch"}, status=400)

        max_concurrent = min(data.get("max_concurrent", 5), 10)
        _fail_fast = data.get("fail_fast", False)  # Preserve accepted input; behavior is unchanged.
        sem = asyncio.Semaphore(max_concurrent)

        async def _execute_op(idx: int, op: dict) -> dict:
            method = op.get("method", "GET").upper()
            path = op.get("path", "")
            body = op.get("body", {})
            op_id = op.get("id", f"op_{idx}")

            if not path:
                return {"id": op_id, "ok": False, "error": "missing path", "status": 400}

            async with sem:
                t0 = ctx.now()
                try:
                    # Build a sub-request to the internal handler.
                    # For safety, only allow internal API paths.
                    if not path.startswith("/v1/") and path not in ("/health", "/metrics"):
                        return {"id": op_id, "ok": False, "error": "only /v1/* and /health paths allowed",
                                "status": 403}

                    # Use aiohttp client to call ourselves (cleanest approach).
                    cfg = request.app[APP_CFG]
                    port = cfg.get("port", 8765)
                    url = f"http://127.0.0.1:{port}{path}"
                    headers = {"Authorization": f"Bearer {cfg['token']}",
                               "Content-Type": "application/json"}

                    async with aiohttp.ClientSession() as session:
                        if method == "GET":
                            async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=30)) as resp:
                                result = await resp.json()
                                return {"id": op_id, "ok": resp.status < 400, "status": resp.status,
                                        "data": result, "duration_ms": round((ctx.now() - t0) * 1000, 2)}
                        if method == "POST":
                            async with session.post(url, headers=headers, json=body,
                                                    timeout=aiohttp.ClientTimeout(total=60)) as resp:
                                result = await resp.json()
                                return {"id": op_id, "ok": resp.status < 400, "status": resp.status,
                                        "data": result, "duration_ms": round((ctx.now() - t0) * 1000, 2)}
                        return {"id": op_id, "ok": False, "error": f"unsupported method: {method}",
                                "status": 405}
                except asyncio.TimeoutError:
                    return {"id": op_id, "ok": False, "error": "timeout", "status": 408,
                            "duration_ms": round((ctx.now() - t0) * 1000, 2)}
                except Exception as e:
                    return {"id": op_id, "ok": False, "error": str(e), "status": 500,
                            "duration_ms": round((ctx.now() - t0) * 1000, 2)}

        # Execute all operations in parallel.
        tasks = [_execute_op(i, op) for i, op in enumerate(operations)]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Process results.
        batch_results = []
        errors = 0
        for r in results:
            if isinstance(r, Exception):
                batch_results.append({"ok": False, "error": str(r), "status": 500})
                errors += 1
            else:
                batch_results.append(r)
                if not r.get("ok", True):
                    errors += 1

        await ctx.emit_event("batch_complete", {"total": len(operations), "errors": errors})

        return ctx.cors_json_response({
            "ok": errors == 0,
            "total": len(operations),
            "success": len(operations) - errors,
            "errors": errors,
            "results": batch_results,
        })

    return BatchHandlers(batch=handle_v1_batch)
