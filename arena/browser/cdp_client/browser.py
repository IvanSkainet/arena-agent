"""Async CDP browser facade."""
from __future__ import annotations

from cdp_browser_modules.common import *  # noqa: F401,F403
from cdp_browser_modules.browser_events import CDPBrowserEventsMixin
from cdp_browser_modules.browser_page import CDPBrowserPageMixin
from cdp_browser_modules.process import launch_browser
from cdp_browser_modules.tabs_http import get_websocket_url
from cdp_browser_modules.websocket_adapter import WebsocketsCDPAdapter


class CDPBrowser(CDPBrowserEventsMixin, CDPBrowserPageMixin):
    """Async Chrome DevTools Protocol browser connection."""
    def __init__(
        self,
        port: int = DEFAULT_PORT,
        headless: bool = True,
        auto_launch: bool = True,
        timeout: float = DEFAULT_TIMEOUT,
        tab_index: int = 0,
    ):
        self.port = port
        self.headless = headless
        self.auto_launch = auto_launch
        self.timeout = timeout
        self.tab_index = tab_index

        self._ws: Optional[aiohttp.ClientWebSocketResponse] = None
        self._session: Optional[aiohttp.ClientSession] = None
        self._req_id = itertools.count(1)
        self._pending: Dict[int, asyncio.Future] = {}
        self._event_handlers: Dict[str, List[Callable]] = {}
        self._listener_task: Optional[asyncio.Task] = None
        self._browser_proc: Optional[subprocess.Popen] = None
        self._closing = False
        self._reconnecting = False

    async def __aenter__(self):
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()

    async def connect(self) -> None:
        """Connect to the browser's CDP WebSocket endpoint."""
        if not HAS_AIOHTTP:
            raise RuntimeError("aiohttp is required for async CDP. Install with: pip install aiohttp")

        ws_url = get_websocket_url(self.port, self.tab_index)

        if ws_url is None and self.auto_launch:
            loop = asyncio.get_running_loop()
            self._browser_proc = await loop.run_in_executor(
                None, launch_browser, self.port, self.headless)
            # Check if browser process died immediately
            if self._browser_proc and self._browser_proc.poll() is not None:
                launch_diag = getattr(self._browser_proc, '_cdp_launch_diag', {})
                raise ConnectionError(
                    f"Browser process exited immediately (rc={self._browser_proc.returncode}). "
                    f"Launch diag: {launch_diag}"
                )
            # Retry until the debug port is ready (up to 15 seconds)
            for _ in range(15):
                ws_url = get_websocket_url(self.port, self.tab_index)
                if ws_url:
                    break
                # Check if browser crashed
                if self._browser_proc and self._browser_proc.poll() is not None:
                    launch_diag = getattr(self._browser_proc, '_cdp_launch_diag', {})
                    raise ConnectionError(
                        f"Browser crashed during startup (rc={self._browser_proc.returncode}). "
                        f"Launch diag: {launch_diag}"
                    )
                await asyncio.sleep(1)

        if ws_url is None:
            raise ConnectionError(f"Cannot connect to browser CDP on port {self.port}")

        self._session = aiohttp.ClientSession()
        try:
            self._ws = await self._session.ws_connect(ws_url, heartbeat=30)
        except Exception:
            await self._session.close()
            raise

        # Start the WebSocket listener FIRST — it must be running to process
        # responses from Page.enable/Runtime.enable. Without this, send()
        # hangs indefinitely waiting for a response that nobody reads.
        self._listener_task = asyncio.create_task(self._listen_loop())

        # Enable core domains (listener is now running to process responses)
        await self.send("Page.enable")
        await self.send("Runtime.enable")

        logger.info("[CDP] Connected to %s", ws_url)

    async def close(self) -> None:
        """Close the WebSocket connection and clean up."""
        self._closing = True

        # Cancel pending futures so callers don't hang
        for msg_id, future in list(self._pending.items()):
            if not future.done():
                future.cancel()
        self._pending.clear()

        # Only cancel listener if we're not inside it (avoid deadlock)
        if self._listener_task and not self._reconnecting:
            self._listener_task.cancel()
            try:
                await self._listener_task
            except asyncio.CancelledError:
                pass

        if self._ws and not self._ws.closed:
            await self._ws.close()

        # _session may be None when using WebsocketsCDPAdapter (Strategy 3)
        if self._session is not None and not self._session.closed:
            await self._session.close()

        if self._browser_proc:
            self._browser_proc.terminate()
            try:
                self._browser_proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._browser_proc.kill()

        self._listener_task = None
        logger.info("[CDP] Connection closed")

    async def reconnect(self) -> None:
        """Attempt to reconnect after a connection drop.

        Called from within _listen_loop, so we must avoid the deadlock
        where close() tries to await the listener task (itself).
        """
        self._reconnecting = True
        self._closing = True

        # Cancel pending futures
        for msg_id, future in list(self._pending.items()):
            if not future.done():
                future.cancel()
        self._pending.clear()

        # Close WS and session without cancelling the listener task
        if self._ws and not self._ws.closed:
            await self._ws.close()
        # _session may be None when using WebsocketsCDPAdapter
        if self._session is not None and not self._session.closed:
            await self._session.close()

        self._closing = False
        self._reconnecting = False

        for attempt in range(1, RECONNECT_ATTEMPTS + 1):
            logger.info("[CDP] Reconnect attempt %d/%d", attempt, RECONNECT_ATTEMPTS)
            try:
                await self.connect()
                return
            except Exception as e:
                logger.warning("[CDP] Reconnect failed: %s", e)
                await asyncio.sleep(RECONNECT_DELAY)
        raise ConnectionError("Failed to reconnect after all attempts")
