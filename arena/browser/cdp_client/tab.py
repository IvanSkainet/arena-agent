"""Single CDP tab abstraction."""
from __future__ import annotations

from cdp_browser_modules.common import *  # noqa: F401,F403
from cdp_browser_modules.tab_connection import CDPTabConnectionMixin
from cdp_browser_modules.tab_ops import CDPTabOpsMixin


class CDPTab(CDPTabConnectionMixin, CDPTabOpsMixin):
    """Represents a single browser tab with an isolated CDP connection."""
    def __init__(
        self,
        target_id: str,
        ws_url: str,
        port: int = DEFAULT_PORT,
        timeout: float = DEFAULT_TIMEOUT,
        title: str = "",
        url: str = "",
    ):
        self.target_id = target_id
        self.ws_url = ws_url
        self.port = port
        self.timeout = timeout
        self.title = title
        self.url = url

        self._browser: Optional[CDPBrowser] = None
        self._connected = False

    def connected(self) -> bool:
        """Whether this tab has an active CDP connection."""
        return self._connected and self._browser is not None

    async def __aenter__(self):
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.disconnect()
