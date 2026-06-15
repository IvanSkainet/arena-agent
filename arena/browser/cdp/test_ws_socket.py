"""WebSocket probe helpers for CDP test-ws diagnostics."""
from __future__ import annotations

import asyncio
import json
import time

import aiohttp

from arena.handler_context import CdpDiagnosticHandlerContext


async def probe_tab_ws(ctx: CdpDiagnosticHandlerContext, tab_ws_url: str, result: dict) -> None:
    if not tab_ws_url:
        result["tab_ws_connect_ok"] = False
        result["tab_ws_connect_error"] = "No tab WS URL available"
        ctx.log_warning("[test-ws] No tab WS URL — cannot test tab WS")
        return

    try:
        import websockets
        result["websockets_available"] = True
        t0 = time.monotonic()
        try:
            ws = await asyncio.wait_for(
                websockets.connect(tab_ws_url, open_timeout=3, close_timeout=2),
                timeout=5,
            )
            elapsed = time.monotonic() - t0
            result["tab_ws_connect_ok"] = True
            result["tab_ws_connect_time_s"] = round(elapsed, 2)
            result["websockets_tab_ok"] = True
            result["websockets_tab_time_s"] = round(elapsed, 2)
            try:
                await ws.send(json.dumps({"id": 1, "method": "Runtime.evaluate", "params": {"expression": "1+1"}}))
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

    if not result["tab_ws_connect_ok"]:
        try:
            t0 = time.monotonic()
            ws_timeout = aiohttp.ClientTimeout(total=3, connect=2, sock_connect=2)
            connector = aiohttp.TCPConnector(force_close=True, enable_cleanup_closed=True)
            async with aiohttp.ClientSession(timeout=ws_timeout, connector=connector) as session:
                tab_ws = await asyncio.wait_for(session.ws_connect(tab_ws_url, heartbeat=None, proxy=None), timeout=5)
                elapsed = time.monotonic() - t0
                result["tab_ws_connect_ok"] = True
                result["tab_ws_connect_time_s"] = round(elapsed, 2)
                try:
                    await tab_ws.send_json({"id": 1, "method": "Runtime.evaluate", "params": {"expression": "1+1"}})
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


async def probe_browser_ws(ctx: CdpDiagnosticHandlerContext, browser_ws_url: str, result: dict) -> None:
    if not browser_ws_url:
        result["ws_connect_ok"] = False
        result["ws_connect_error"] = "No browser WS URL available"
        return

    try:
        import websockets
        t0 = time.monotonic()
        try:
            ws = await asyncio.wait_for(
                websockets.connect(browser_ws_url, open_timeout=3, close_timeout=2),
                timeout=5,
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
