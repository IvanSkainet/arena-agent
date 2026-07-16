"""Handlers for MCP Streamable HTTP, SSE and WebSocket transports."""
from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from typing import Any

import aiohttp
from aiohttp import web
from arena.app_keys import APP_MCP_SESSIONS

from arena.handler_context import McpHandlerContext
from arena.mcp.runtime import now_ms, sid
from arena.handler_helpers import authed, err_json


@dataclass(frozen=True)
class McpHandlers:
    mcp_post: object
    mcp_delete: object
    sse: object
    sse_messages: object
    ws: object


def make_mcp_handlers(ctx: McpHandlerContext) -> McpHandlers:
    @authed(ctx)
    async def handle_mcp_post(request: web.Request) -> web.Response:
        """MCP Streamable HTTP — main endpoint."""
        try:
            msg = await request.json()
        except Exception:
            ctx.record_request(is_error=True, count_request=False)
            return ctx.cors_json_response({"jsonrpc": "2.0", "error": {"code": -32700, "message": "Parse error"}}, status=400)

        # New session on initialize.
        session_hdr = request.headers.get("Mcp-Session-Id", "")
        if msg.get("method") == "initialize":
            session = sid()
            request.app[APP_MCP_SESSIONS][session] = {"created": now_ms()}
            resp = ctx.handle_rpc(msg)
            return web.json_response(resp, headers={
                "Mcp-Session-Id": session,
                "Access-Control-Allow-Origin": "*",
            })

        resp = ctx.handle_rpc(msg)
        if resp is None:
            return web.Response(status=204, headers={"Access-Control-Allow-Origin": "*"})
        return web.json_response(resp, headers={"Access-Control-Allow-Origin": "*"})

    @authed(ctx)
    async def handle_mcp_delete(request: web.Request) -> web.Response:
        """Close MCP session."""
        r = ctx.require_auth(request)
        if r:
            return r
        try:
            sess = request.headers.get("Mcp-Session-Id", "")
            request.app[APP_MCP_SESSIONS].pop(sess, None)
            return web.Response(status=204, headers={"Access-Control-Allow-Origin": "*"})
        except Exception as e:
            return ctx.cors_json_response({"ok": False, "error": str(e)}, status=500)

    async def handle_sse(request: web.Request) -> web.Response:
        """SSE transport — open event stream."""
        session = sid()
        request.app[APP_MCP_SESSIONS][session] = {"created": now_ms()}

        resp = web.StreamResponse(
            status=200,
            headers={
                "Content-Type": "text/event-stream",
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "Access-Control-Allow-Origin": request.headers.get("Origin", "*"),
                "Access-Control-Allow-Methods": "GET, POST, DELETE, OPTIONS",
                "Access-Control-Allow-Headers": "Content-Type, Mcp-Session-Id, Last-Event-ID, Authorization",
                "Access-Control-Expose-Headers": "Mcp-Session-Id",
            },
        )
        await resp.prepare(request)
        await resp.write(f"event: endpoint\ndata: /messages?session_id={session}\n\n".encode())

        # Keep alive with periodic pings.
        try:
            while True:
                await asyncio.sleep(15)
                await resp.write(b": keepalive\n\n")
        except (ConnectionResetError, asyncio.CancelledError):
            pass
        finally:
            request.app[APP_MCP_SESSIONS].pop(session, None)

        return resp

    @authed(ctx)
    async def handle_sse_messages(request: web.Request) -> web.Response:
        """SSE peer message endpoint."""
        try:
            msg = await request.json()
        except Exception:
            ctx.record_request(is_error=True, count_request=False)
            return ctx.cors_json_response({"jsonrpc": "2.0", "error": {"code": -32700, "message": "Parse error"}}, status=400)

        # Process the RPC message.
        ctx.handle_rpc(msg)
        return web.Response(status=202, headers={"Access-Control-Allow-Origin": "*"})

    async def handle_ws(request: web.Request) -> web.WebSocketResponse:
        """WebSocket MCP transport — full-duplex JSON-RPC."""
        r = ctx.require_auth(request)
        if r:
            ws = web.WebSocketResponse()
            await ws.prepare(request)
            await ws.send_json({"jsonrpc": "2.0", "error": {"code": -32001, "message": "unauthorized"}})
            await ws.close()
            return ws
        ctx.record_request()
        ws = web.WebSocketResponse()
        await ws.prepare(request)

        async for msg in ws:
            if msg.type == aiohttp.WSMsgType.TEXT:
                try:
                    data = json.loads(msg.data)
                    method = data.get("method", "")

                    # Subscribe/unsubscribe extension.
                    if method == "subscribe":
                        await ws.send_json({"jsonrpc": "2.0", "id": data.get("id"),
                                            "result": {"subscribed": (data.get("params") or {}).get("topic", "default")}})
                        continue
                    if method == "unsubscribe":
                        await ws.send_json({"jsonrpc": "2.0", "id": data.get("id"),
                                            "result": {"unsubscribed": True}})
                        continue

                    resp = ctx.handle_rpc(data)
                    if resp is not None:
                        await ws.send_json(resp)
                except Exception as e:
                    await ws.send_json({"jsonrpc": "2.0", "error": {"code": -32603, "message": str(e)}})

            elif msg.type == aiohttp.WSMsgType.ERROR:
                ctx.log_error("[WS] Connection error: %s", ws.exception())
                break
            elif msg.type == aiohttp.WSMsgType.CLOSE:
                break

        return ws

    return McpHandlers(
        mcp_post=handle_mcp_post,
        mcp_delete=handle_mcp_delete,
        sse=handle_sse,
        sse_messages=handle_sse_messages,
        ws=handle_ws,
    )
