"""CDP tab manager component."""
from __future__ import annotations

from arena.browser.cdp_client.common import *  # noqa: F401,F403
from arena.browser.cdp_client.process import launch_browser
from arena.browser.cdp_client.tab import CDPTab
from arena.browser.cdp_client.tabs_http import close_tab, get_new_tab_url, list_tabs
from arena.browser.cdp_client.websocket_adapter import WebsocketsCDPAdapter

class CDPTabManagerBrowserEventsMixin:
    async def _browser_send(self, method: str, params: Optional[Dict] = None,
                            timeout: Optional[float] = None) -> Dict:
        """Send a CDP command on the browser-level WebSocket."""
        if not self._browser_ws or self._browser_ws.closed:
            raise ConnectionError("Browser WebSocket is not connected")

        msg_id = next(self._browser_req_id)
        msg = {"id": msg_id, "method": method}
        if params:
            msg["params"] = params

        loop = asyncio.get_running_loop()
        future = loop.create_future()
        self._browser_pending[msg_id] = future

        await self._browser_ws.send_json(msg)
        logger.debug("[CDPTabManager:BrowserWS] -> %s %s (id=%d)", method, params or "", msg_id)

        effective_timeout = timeout or self.timeout
        try:
            return await asyncio.wait_for(future, effective_timeout)
        except asyncio.TimeoutError:
            self._browser_pending.pop(msg_id, None)
            raise

    async def _browser_listen_loop(self) -> None:
        """Background task: listen for browser-level CDP events (Target.*)."""
        # Same type handling as _listen_loop for WebsocketsCDPAdapter compatibility
        TEXT_TYPE = aiohttp.WSMsgType.TEXT if HAS_AIOHTTP else 1
        CLOSED_TYPES = set()
        if HAS_AIOHTTP:
            CLOSED_TYPES.add(aiohttp.WSMsgType.CLOSED)
            CLOSED_TYPES.add(aiohttp.WSMsgType.ERROR)
        CLOSED_TYPES.add(0x100)  # WebsocketsCDPAdapter sentinel
        CLOSED_TYPES.add(-1)

        try:
            async for msg in self._browser_ws:
                if msg.type == TEXT_TYPE:
                    try:
                        data = json.loads(msg.data)
                    except json.JSONDecodeError:
                        continue

                    # Handle responses to our browser-level commands
                    msg_id = data.get("id")
                    if msg_id and msg_id in self._browser_pending:
                        future = self._browser_pending.pop(msg_id)
                        if not future.done():
                            future.set_result(data)
                        continue

                    # Handle Target domain events
                    method = data.get("method", "")
                    params = data.get("params", {})

                    if method == "Target.targetCreated":
                        await self._handle_target_created(params)
                    elif method == "Target.targetDestroyed":
                        await self._handle_target_destroyed(params)
                    elif method == "Target.targetInfoChanged":
                        await self._handle_target_info_changed(params)

                elif msg.type in CLOSED_TYPES:
                    break
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error("[CDPTabManager:BrowserWS] Listener error: %s", e)
