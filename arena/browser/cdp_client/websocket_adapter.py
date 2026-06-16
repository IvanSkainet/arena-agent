"""Extracted module from scripts/cdp_browser.py."""
from __future__ import annotations

from arena.browser.cdp_client.common import *  # noqa: F401,F403

class WebsocketsCDPAdapter:
    """Adapter that wraps a `websockets` connection to provide the same interface
    as aiohttp's ClientWebSocketResponse.

    This allows CDPBrowser to use the `websockets` library when aiohttp's
    ws_connect hangs or fails (known issue with some Python 3.14 + aiohttp
    combinations and certain Chromium headless versions).

    Attributes provided:
        closed: bool — whether the WS is closed
    """

    def __init__(self, ws):
        self._ws = ws
        self._closed = False

    @property
    def closed(self) -> bool:
        return self._closed

    async def send_json(self, data: dict) -> None:
        """Send a JSON message (same interface as aiohttp WS)."""
        if self._closed:
            raise ConnectionError("WebSocket is closed")
        await self._ws.send(json.dumps(data))

    async def receive(self, timeout: float = 30) -> Any:
        """Receive a message. Returns a message-like object with .type and .data.

        For aiohttp compatibility, we return a simple namespace with:
            .type — mapped to aiohttp WSMsgType values
            .data — the message data string
        """
        try:
            raw = await asyncio.wait_for(self._ws.recv(), timeout=timeout)
            # websockets returns str for text messages
            return _WSMessage(type=aiohttp.WSMsgType.TEXT if HAS_AIOHTTP else 1, data=raw)
        except asyncio.TimeoutError:
            return _WSMessage(type=0x100 if HAS_AIOHTTP else -1, data="")  # CLOSED/timeout
        except _websockets_mod.ConnectionClosed:
            self._closed = True
            return _WSMessage(type=0x100 if HAS_AIOHTTP else -1, data="")

    async def close(self) -> None:
        """Close the WebSocket connection."""
        if not self._closed:
            try:
                await self._ws.close()
            except Exception:
                pass
            self._closed = True

    def __aiter__(self):
        return self

    async def __anext__(self):
        msg = await self.receive(timeout=60)
        if hasattr(aiohttp, 'WSMsgType') and msg.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
            raise StopAsyncIteration
        elif msg.type in (0x100, -1):  # Our sentinel for closed/error
            raise StopAsyncIteration
        return msg

class _WSMessage:
    """Simple message object compatible with aiohttp's WSMessage."""
    def __init__(self, type, data):
        self.type = type
        self.data = data
