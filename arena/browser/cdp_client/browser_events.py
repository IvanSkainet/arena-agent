"""Extracted CDP browser component."""
from __future__ import annotations

from cdp_browser_modules.common import *  # noqa: F401,F403
from cdp_browser_modules.process import launch_browser
from cdp_browser_modules.tabs_http import get_websocket_url, list_tabs, get_new_tab_url, close_tab
from cdp_browser_modules.websocket_adapter import WebsocketsCDPAdapter

class CDPBrowserEventsMixin:
    async def send(self, method: str, params: Optional[Dict] = None,
                   timeout: Optional[float] = None) -> Dict:
        """Send a CDP command and wait for its response.

        Args:
            method: CDP method name (e.g., "Page.navigate")
            params: Optional parameters dict
            timeout: Override default timeout for this call

        Returns:
            The CDP response dict (with "id" and "result" or "error")

        Raises:
            asyncio.TimeoutError: if the response doesn't arrive in time
            ConnectionError: if the WebSocket is closed
        """
        if not self._ws or self._ws.closed:
            raise ConnectionError("WebSocket is not connected")

        msg_id = next(self._req_id)
        msg = {"id": msg_id, "method": method}
        if params:
            msg["params"] = params

        loop = asyncio.get_running_loop()
        future = loop.create_future()
        self._pending[msg_id] = future

        await self._ws.send_json(msg)
        logger.debug("[CDP] -> %s %s (id=%d)", method, params or "", msg_id)

        effective_timeout = timeout or self.timeout
        try:
            result = await asyncio.wait_for(future, effective_timeout)
            if "error" in result:
                logger.warning("[CDP] Error response for %s: %s", method, result["error"])
            return result
        except asyncio.TimeoutError:
            self._pending.pop(msg_id, None)
            raise
        except Exception:
            self._pending.pop(msg_id, None)
            raise

    def on(self, event_name: str, callback: Callable[[Dict], Any]) -> None:
        """Register a callback for a CDP event.

        Args:
            event_name: CDP event name (e.g., "Page.loadEventFired")
            callback: Function to call with the event params dict
        """
        self._event_handlers.setdefault(event_name, []).append(callback)

    def off(self, event_name: str, callback: Callable) -> None:
        """Unregister a callback for a CDP event."""
        handlers = self._event_handlers.get(event_name, [])
        if callback in handlers:
            handlers.remove(callback)

    async def wait_for_event(self, event_name: str, timeout: Optional[float] = None) -> Dict:
        """Wait for a specific CDP event and return its params.

        This is a convenience method that creates a one-shot listener.
        """
        effective_timeout = timeout or self.timeout
        loop = asyncio.get_running_loop()
        future = loop.create_future()

        def one_shot(params: Dict):
            if not future.done():
                future.set_result(params)

        self.on(event_name, one_shot)
        try:
            return await asyncio.wait_for(future, effective_timeout)
        finally:
            self.off(event_name, one_shot)

    async def _listen_loop(self) -> None:
        """Background task that reads WebSocket messages and dispatches them."""
        # Determine TEXT/CLOSED/ERROR type constants based on WS implementation
        # (WebsocketsCDPAdapter returns _WSMessage with our sentinel values)
        TEXT_TYPE = aiohttp.WSMsgType.TEXT if HAS_AIOHTTP else 1
        CLOSED_TYPES = set()
        if HAS_AIOHTTP:
            CLOSED_TYPES.add(aiohttp.WSMsgType.CLOSED)
            CLOSED_TYPES.add(aiohttp.WSMsgType.ERROR)
        CLOSED_TYPES.add(0x100)  # Our WebsocketsCDPAdapter sentinel
        CLOSED_TYPES.add(-1)    # Fallback sentinel

        try:
            async for msg in self._ws:
                if msg.type == TEXT_TYPE:
                    try:
                        data = json.loads(msg.data)
                    except json.JSONDecodeError:
                        continue

                    # Dispatch response to pending future
                    msg_id = data.get("id")
                    if msg_id and msg_id in self._pending:
                        future = self._pending.pop(msg_id)
                        if not future.done():
                            future.set_result(data)
                        continue

                    # Dispatch event to handlers
                    method = data.get("method")
                    if method:
                        params = data.get("params", {})
                        # Call registered handlers
                        for handler in self._event_handlers.get(method, []):
                            try:
                                result = handler(params)
                                if asyncio.iscoroutine(result):
                                    asyncio.create_task(result)
                            except Exception as e:
                                logger.error("[CDP] Event handler error for %s: %s", method, e)

                elif msg.type in CLOSED_TYPES:
                    logger.warning("[CDP] WebSocket closed/error")
                    break
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error("[CDP] Listener error: %s", e)

        # If we got here unexpectedly, try reconnect
        if not self._closing:
            logger.info("[CDP] Connection lost, attempting reconnect...")
            try:
                await self.reconnect()
            except ConnectionError:
                logger.error("[CDP] Reconnect failed")
