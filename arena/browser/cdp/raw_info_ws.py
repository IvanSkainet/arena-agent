"""WebSocket probing helpers for CDP raw-info diagnostics."""
from __future__ import annotations

import asyncio
import json
import time

import aiohttp

from arena.handler_context import CdpDiagnosticHandlerContext


def select_tab_ws_url(page_tabs: list[dict], port: int, result: dict) -> str:
    """Select or construct the first page tab WebSocket URL for probing."""
    if not page_tabs:
        return ""
    tab_id = page_tabs[0].get("id", "")
    tab_ws_url = page_tabs[0].get("webSocketDebuggerUrl", "")
    if not tab_ws_url and tab_id:
        tab_ws_url = f"ws://127.0.0.1:{port}/devtools/page/{tab_id}"
        result["tab_ws_url_constructed"] = True
    result["tab_ws_url_tested"] = tab_ws_url
    return tab_ws_url


async def probe_with_websockets(tab_ws_url: str, result: dict) -> None:
    """Try the third-party websockets client first."""
    try:
        import websockets

        t0 = time.monotonic()
        ws = await asyncio.wait_for(
            websockets.connect(tab_ws_url, open_timeout=3, close_timeout=2),
            timeout=5,
        )
        elapsed = time.monotonic() - t0
        result["tab_ws_ok"] = True
        result["tab_ws_time_s"] = round(elapsed, 2)
        result["tab_ws_lib"] = "websockets"
        try:
            await ws.send(json.dumps({"id": 1, "method": "Runtime.evaluate", "params": {"expression": "1+1"}}))
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


async def probe_with_aiohttp(tab_ws_url: str, result: dict) -> None:
    """Fallback WebSocket probe using aiohttp."""
    try:
        t0 = time.monotonic()
        ws_timeout = aiohttp.ClientTimeout(total=3, connect=2, sock_connect=2)
        connector = aiohttp.TCPConnector(force_close=True)
        async with aiohttp.ClientSession(timeout=ws_timeout, connector=connector) as session:
            tab_ws = await asyncio.wait_for(
                session.ws_connect(tab_ws_url, heartbeat=None, proxy=None),
                timeout=5,
            )
            elapsed = time.monotonic() - t0
            result["tab_ws_ok"] = True
            result["tab_ws_time_s"] = round(elapsed, 2)
            result["tab_ws_lib"] = "aiohttp"
            try:
                await tab_ws.send_json({"id": 1, "method": "Runtime.evaluate", "params": {"expression": "1+1"}})
                msg = await asyncio.wait_for(tab_ws.receive(), timeout=3)
                if msg.type == aiohttp.WSMsgType.TEXT:
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


async def probe_raw_info_websocket(ctx: CdpDiagnosticHandlerContext, page_tabs: list[dict], port: int, result: dict) -> None:
    """Run the raw-info tab WebSocket probe, with aiohttp fallback."""
    tab_ws_url = select_tab_ws_url(page_tabs, port, result)
    if not tab_ws_url:
        return

    await probe_with_websockets(tab_ws_url, result)
    if not result.get("tab_ws_ok"):
        await probe_with_aiohttp(tab_ws_url, result)
