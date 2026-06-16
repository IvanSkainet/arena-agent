"""CDP tab manager component."""
from __future__ import annotations

from arena.browser.cdp_client.common import *  # noqa: F401,F403
from arena.browser.cdp_client.process import launch_browser
from arena.browser.cdp_client.tab import CDPTab
from arena.browser.cdp_client.tabs_http import close_tab, get_new_tab_url, list_tabs
from arena.browser.cdp_client.websocket_adapter import WebsocketsCDPAdapter

class CDPTabManagerTabLifecycleMixin:
    async def new_tab(self, url: str = "about:blank", activate: bool = True) -> CDPTab:
        """Create a new browser tab and return a CDPTab for it.

        Args:
            url: Initial URL for the new tab (default: about:blank)
            activate: If True, set the new tab as the active tab (default: True)

        Returns:
            CDPTab instance for the new tab

        Raises:
            ConnectionError: if tab creation fails
        """
        # Use HTTP endpoint to create the tab
        ws_url = get_new_tab_url(self.port)
        if not ws_url:
            raise ConnectionError("Failed to create new tab")

        # Extract target ID from WebSocket URL
        # Format: ws://127.0.0.1:9222/devtools/page/{TARGET_ID}
        target_id = ws_url.rstrip("/").split("/")[-1]

        # Create CDPTab
        tab = CDPTab(
            target_id=target_id,
            ws_url=ws_url,
            port=self.port,
            timeout=self.timeout,
            url=url,
        )

        # Register in tab map BEFORE connecting, so _handle_target_created's
        # early-return on "already tracked" prevents duplicate registration
        self._tabs[target_id] = tab

        # Connect to the new tab (with timeout)
        await asyncio.wait_for(tab.connect(), timeout=self.timeout)

        # Navigate if URL specified
        if url and url != "about:blank":
            await tab.navigate(url, wait=True)

        if activate:
            self._active_tab_id = target_id

        logger.info("[CDPTabManager] New tab created and connected: %s → %s", target_id, url)
        return tab

    async def close_tab(self, target_id: str) -> bool:
        """Close a browser tab and clean up its CDPTab connection.

        Args:
            target_id: The target ID of the tab to close

        Returns:
            True if the tab was closed successfully
        """
        tab = self._tabs.get(target_id)
        if tab is None:
            # Try closing via HTTP anyway
            return close_tab(target_id, self.port)

        # Disconnect our CDP connection first
        if tab.connected:
            await tab.disconnect()

        # Close the browser tab via HTTP
        success = close_tab(target_id, self.port)

        # Remove from tracking
        self._tabs.pop(target_id, None)

        # Update active tab
        if self._active_tab_id == target_id:
            self._active_tab_id = None
            if self._tabs:
                self._active_tab_id = next(iter(self._tabs))

        logger.info("[CDPTabManager] Tab closed: %s (success=%s)", target_id, success)
        return success

    def activate(self, target_id: str) -> bool:
        """Set a tab as the active tab.

        Args:
            target_id: The target ID of the tab to activate

        Returns:
            True if the tab was found and activated
        """
        if target_id in self._tabs:
            self._active_tab_id = target_id
            logger.info("[CDPTabManager] Activated tab: %s", target_id)
            return True
        logger.warning("[CDPTabManager] Cannot activate unknown tab: %s", target_id)
        return False
