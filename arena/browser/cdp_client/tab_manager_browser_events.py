"""CDP tab manager component."""
from __future__ import annotations

import itertools
from typing import TYPE_CHECKING

from arena.browser.cdp_client.common import (
    HAS_AIOHTTP,
    Any,
    Dict,
    Optional,
    aiohttp,
    asyncio,
    json,
    logger,
)


class CDPTabManagerBrowserEventsMixin:
    if TYPE_CHECKING:  # pragma: no cover - typing only
        # Supplied by the concrete class that mixes this in. Declared, not
        # assigned: annotations only, so runtime behaviour is unchanged.
        # Written down because an undeclared interface lets a real typo
        # hide among the noise it generates.
        _browser_pending: Dict[int, asyncio.Future]
        _browser_req_id: itertools.count[int]
        _browser_ws: Any
        async def _handle_target_created(self, params: Dict) -> None: ...
        async def _handle_target_destroyed(self, params: Dict) -> None: ...
        async def _handle_target_info_changed(self, params: Dict) -> None: ...
        timeout: float

    async def _browser_send(self, method: str, params: Optional[Dict] = None,
                            timeout: Optional[float] = None) -> Dict:
        """Send a CDP command on the browser-level WebSocket."""
        if not self._browser_ws or self._browser_ws.closed:
            raise ConnectionError("Browser WebSocket is not connected")

        msg_id = next(self._browser_req_id)
        # int | str | dict: the params payload is added below.
        msg: Dict[str, Any] = {"id": msg_id, "method": method}
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

        # Same invariant as CDPBrowser._listen_loop: the task is scheduled
        # only after the browser-level WebSocket has connected.
        assert self._browser_ws is not None
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
