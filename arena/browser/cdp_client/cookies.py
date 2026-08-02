"""High-level CDP cookie manager."""
from __future__ import annotations

from typing import TYPE_CHECKING

from arena.browser.cdp_client.common import Dict, List, logger

if TYPE_CHECKING:  # pragma: no cover - typing only
    # CDPBrowser is referenced solely in annotations here, and
    # `from __future__ import annotations` keeps those as strings,
    # so a runtime import would only add an import cycle for nothing.
    from arena.browser.cdp_client.browser import CDPBrowser
from arena.browser.cdp_client.cookie_crud import CDPCookieCrudMixin
from arena.browser.cdp_client.cookie_profiles import CDPCookieProfileMixin


class CDPCookieManager(CDPCookieCrudMixin, CDPCookieProfileMixin):
    """High-level cookie operations for an active CDP browser session."""
    def __init__(self, browser: CDPBrowser):
        self._browser = browser
        self._profiles: Dict[str, List[Dict]] = {}
        self._active = False

    async def start(self) -> None:
        """Enable cookie management (ensures Network domain is enabled)."""
        if self._active:
            return
        # Network.enable is idempotent if already enabled
        await self._browser.send("Network.enable")
        self._active = True
        logger.info("[CDPCookieManager] Started")

    async def stop(self) -> None:
        """Stop cookie management (does NOT disable Network domain)."""
        # Don't disable Network — other consumers may need it
        self._active = False
        logger.info("[CDPCookieManager] Stopped")

    def active(self) -> bool:
        """Whether cookie management is active."""
        return self._active
