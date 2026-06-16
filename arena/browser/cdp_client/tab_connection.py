"""Single CDP tab component."""
from __future__ import annotations

from arena.browser.cdp_client.common import *  # noqa: F401,F403
from arena.browser.cdp_client.websocket_adapter import WebsocketsCDPAdapter

class CDPTabConnectionMixin:
    async def connect(self) -> None:
        """Establish a CDP WebSocket connection to this tab.

        v1.9.19: Added traceback logging for every failed strategy.
        Reordered strategies — try websockets library FIRST since
        aiohttp ws_connect is known to hang on Python 3.14. Also reduced
        per-strategy timeouts to 5s to prevent total connect from taking
        more than 20s.
        """
        if self._connected and self._browser is not None:
            return

        if not HAS_AIOHTTP:
            raise RuntimeError("aiohttp is required for CDPTab. Install with: pip install aiohttp")

        logger.info("[CDPTab] Connecting to tab %s WS URL: %s", self.target_id, self.ws_url)

        # Create a CDPBrowser instance configured for this specific tab
        self._browser = CDPBrowser(
            port=self.port,
            auto_launch=False,  # Don't auto-launch — tab already exists
            timeout=self.timeout,
        )

        ws_connected = False
        last_error = None

        # v1.9.18: Strategy 1 — websockets library FIRST
        # On Python 3.14, aiohttp ws_connect is known to hang indefinitely
        # even with timeouts. The websockets library uses a completely
        # different implementation and is more reliable.
        if HAS_WEBSOCKETS:
            try:
                logger.info("[CDPTab] Strategy 1: websockets library (fastest, most reliable on Py3.14)")
                ws_raw = await asyncio.wait_for(
                    _websockets_mod.connect(self.ws_url, open_timeout=5, close_timeout=3),
                    timeout=7
                )
                logger.info("[CDPTab] Strategy 1 SUCCESS: websockets connected to %s", self.target_id)
                self._browser._ws = WebsocketsCDPAdapter(ws_raw)
                self._browser._session = None
                ws_connected = True
                logger.info("[CDPTab] Using websockets adapter for tab %s", self.target_id)
            except asyncio.TimeoutError:
                logger.warning("[CDPTab] Strategy 1 TIMED OUT (7s) — websockets library")
                last_error = f"websockets library timed out (7s). URL: {self.ws_url}"
            except ImportError:
                logger.info("[CDPTab] websockets library not available for Strategy 1")
                last_error = "websockets library not available"
            except Exception as e:
                logger.warning("[CDPTab] Strategy 1 FAILED: %s — websockets library\n%s", e, traceback.format_exc())
                last_error = f"websockets error: {type(e).__name__}: {e}. URL: {self.ws_url}"

        # Strategy 2: aiohttp with force_close connector, no proxy, NO heartbeat
        if not ws_connected:
            try:
                logger.info("[CDPTab] Strategy 2: aiohttp TCPConnector(force_close), no proxy, no heartbeat")
                ws_timeout = aiohttp.ClientTimeout(total=5, connect=3, sock_connect=3)
                connector = aiohttp.TCPConnector(force_close=True, enable_cleanup_closed=True)
                self._browser._session = aiohttp.ClientSession(
                    timeout=ws_timeout, connector=connector
                )
                self._browser._ws = await asyncio.wait_for(
                    self._browser._session.ws_connect(
                        self.ws_url, heartbeat=None,
                        proxy=None,
                    ),
                    timeout=5
                )
                ws_connected = True
                logger.info("[CDPTab] Strategy 2 SUCCESS: Tab %s WS connected", self.target_id)
            except asyncio.TimeoutError:
                logger.warning("[CDPTab] Strategy 2 TIMED OUT (5s) — URL: %s", self.ws_url)
                last_error = f"aiohttp ws_connect timed out (5s). URL: {self.ws_url}"
                if self._browser._session and not self._browser._session.closed:
                    await self._browser._session.close()
            except Exception as e:
                logger.warning("[CDPTab] Strategy 2 FAILED: %s — URL: %s\n%s", e, self.ws_url, traceback.format_exc())
                last_error = f"aiohttp ws_connect error: {type(e).__name__}: {e}. URL: {self.ws_url}"
                if self._browser._session and not self._browser._session.closed:
                    await self._browser._session.close()

        # Strategy 3: aiohttp default connector with heartbeat (last resort)
        if not ws_connected:
            try:
                logger.info("[CDPTab] Strategy 3: aiohttp with heartbeat=30")
                ws_timeout = aiohttp.ClientTimeout(total=8, connect=5, sock_connect=5)
                self._browser._session = aiohttp.ClientSession(timeout=ws_timeout)
                self._browser._ws = await asyncio.wait_for(
                    self._browser._session.ws_connect(self.ws_url, heartbeat=30, proxy=None),
                    timeout=8
                )
                ws_connected = True
                logger.info("[CDPTab] Strategy 3 SUCCESS: Tab %s WS connected", self.target_id)
            except asyncio.TimeoutError:
                logger.warning("[CDPTab] Strategy 3 TIMED OUT (8s)")
                last_error = f"aiohttp+heartbeat ws_connect timed out (8s). URL: {self.ws_url}"
                if self._browser._session and not self._browser._session.closed:
                    await self._browser._session.close()
            except Exception as e:
                logger.warning("[CDPTab] Strategy 3 FAILED: %s\n%s", e, traceback.format_exc())
                last_error = f"aiohttp+heartbeat error: {type(e).__name__}: {e}. URL: {self.ws_url}"
                if self._browser._session and not self._browser._session.closed:
                    await self._browser._session.close()

        # Strategy 4: websockets library if not tried yet
        if not ws_connected and not HAS_WEBSOCKETS:
            logger.info("[CDPTab] websockets library not available, all aiohttp strategies failed")
            last_error = f"All aiohttp strategies failed. websockets library not installed. {last_error}"

        if not ws_connected:
            self._browser = None
            raise ConnectionError(
                f"Tab {self.target_id} WebSocket connect FAILED after all strategies. "
                f"Last error: {last_error}. "
                f"HTTP works (list_tabs succeeds) but WebSocket upgrade fails. "
                f"This suggests a Chromium headless mode or aiohttp compatibility issue."
            )

        # Disable auto-reconnect: if WS drops, _listen_loop would call
        # reconnect() which connects to tab_index=0, NOT this tab.
        # Instead, let CDPTabManager handle reconnection at its level.
        self._browser._closing = True  # Prevents _listen_loop from calling reconnect

        # CRITICAL (v1.9.21): Start the listener loop BEFORE sending any CDP
        # commands. The send() method awaits a response, which is resolved by
        # the listener loop receiving incoming messages. If the listener isn't
        # running, send() hangs indefinitely — this was the root cause of the
        # "Active tab is not connected" bug through v1.9.20.
        self._browser._listener_task = asyncio.create_task(self._browser._listen_loop())

        # Enable core domains (now the listener can process responses)
        await self._browser.send("Page.enable")
        await self._browser.send("Runtime.enable")

        self._connected = True
        logger.info("[CDPTab] Connected to tab %s (%s)", self.target_id, self.title or self.url)

    async def disconnect(self) -> None:
        """Disconnect from this tab (does NOT close the browser tab)."""
        if self._browser:
            await self._browser.close()
            self._browser = None
        self._connected = False
        logger.info("[CDPTab] Disconnected from tab %s", self.target_id)

    async def refresh_info(self) -> Dict[str, str]:
        """Refresh title and URL from the live page.

        Returns:
            Dict with 'title' and 'url' keys.
        """
        if not self._connected:
            return {"title": self.title, "url": self.url}

        try:
            self.title = await self.get_title() or self.title
            self.url = await self.get_current_url() or self.url
        except Exception:
            pass
        return {"title": self.title, "url": self.url}

    async def send(self, method: str, params: Optional[Dict] = None,
                   timeout: Optional[float] = None) -> Dict:
        """Send a raw CDP command via this tab's connection."""
        if not self._connected or not self._browser:
            raise ConnectionError(f"Tab {self.target_id} is not connected")
        return await self._browser.send(method, params, timeout)

    def on(self, event_name: str, callback: Callable[[Dict], Any]) -> None:
        """Register a callback for a CDP event on this tab."""
        if not self._browser:
            raise ConnectionError(f"Tab {self.target_id} is not connected")
        self._browser.on(event_name, callback)

    def off(self, event_name: str, callback: Callable) -> None:
        """Unregister a callback for a CDP event on this tab."""
        if self._browser:
            self._browser.off(event_name, callback)

    async def wait_for_event(self, event_name: str,
                             timeout: Optional[float] = None) -> Dict:
        """Wait for a specific CDP event on this tab."""
        if not self._connected or not self._browser:
            raise ConnectionError(f"Tab {self.target_id} is not connected")
        return await self._browser.wait_for_event(event_name, timeout)
