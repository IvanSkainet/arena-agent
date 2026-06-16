"""High-level CDP tab manager facade."""
from __future__ import annotations

from arena.browser.cdp_client.common import *  # noqa: F401,F403
from arena.browser.cdp_client.tab_manager_browser_ws import CDPTabManagerBrowserWsMixin
from arena.browser.cdp_client.tab_manager_callbacks import CDPTabManagerCallbackMixin
from arena.browser.cdp_client.tab_manager_connect import CDPTabManagerConnectMixin
from arena.browser.cdp_client.tab_manager_ops import CDPTabManagerOpsMixin
from arena.browser.cdp_client.tab_manager_targets import CDPTabManagerTargetMixin


class CDPTabManager(
    CDPTabManagerConnectMixin,
    CDPTabManagerBrowserWsMixin,
    CDPTabManagerTargetMixin,
    CDPTabManagerOpsMixin,
    CDPTabManagerCallbackMixin,
):
    """Manages multiple browser tabs via Chrome DevTools Protocol."""
    def __init__(
        self,
        port: int = DEFAULT_PORT,
        headless: bool = True,
        auto_launch: bool = True,
        timeout: float = DEFAULT_TIMEOUT,
        auto_discover_existing: bool = True,
    ):
        self.port = port
        self.headless = headless
        self.auto_launch = auto_launch
        self.timeout = timeout
        self.auto_discover_existing = auto_discover_existing

        self._tabs: Dict[str, CDPTab] = {}  # target_id → CDPTab
        self._active_tab_id: Optional[str] = None
        self._browser_proc: Optional[subprocess.Popen] = None
        self._closing = False

        # Browser-level WebSocket for Target.* events
        self._browser_ws: Optional[aiohttp.ClientWebSocketResponse] = None
        self._browser_session: Optional[aiohttp.ClientSession] = None
        self._browser_listener_task: Optional[asyncio.Task] = None
        self._browser_req_id = itertools.count(1)
        self._browser_pending: Dict[int, asyncio.Future] = {}

        # Lifecycle event callbacks
        self._tab_created_callbacks: List[Callable] = []
        self._tab_destroyed_callbacks: List[Callable] = []
        self._tab_navigated_callbacks: List[Callable] = []

        # Track fire-and-forget callback tasks for cleanup
        self._callback_tasks: List[asyncio.Task] = []

        # WS diagnostics — populated during connect() for API response
        self.ws_diagnostics: Dict[str, Any] = {}

    async def __aenter__(self):
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()

    def __del__(self):
        if self._browser_proc or self._browser_session:
            logger.warning(
                "CDPTabManager was not properly closed. "
                "Call 'await mgr.close()' or use 'async with'."
            )

    def active_tab(self) -> Optional[CDPTab]:
        """Get the currently active tab."""
        if self._active_tab_id and self._active_tab_id in self._tabs:
            return self._tabs[self._active_tab_id]
        return None

    def tab_count(self) -> int:
        """Number of tracked tabs."""
        return len(self._tabs)

    def active_tab_id(self) -> Optional[str]:
        """Get the target ID of the currently active tab."""
        return self._active_tab_id
