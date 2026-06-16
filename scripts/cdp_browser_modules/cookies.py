"""High-level CDP cookie manager."""
from __future__ import annotations

from cdp_browser_modules.common import *  # noqa: F401,F403
from cdp_browser_modules.cookie_crud import CDPCookieCrudMixin
from cdp_browser_modules.cookie_profiles import CDPCookieProfileMixin


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
