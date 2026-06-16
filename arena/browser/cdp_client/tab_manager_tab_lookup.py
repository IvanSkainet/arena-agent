"""CDP tab manager component."""
from __future__ import annotations

from arena.browser.cdp_client.common import *  # noqa: F401,F403
from arena.browser.cdp_client.process import launch_browser
from arena.browser.cdp_client.tab import CDPTab
from arena.browser.cdp_client.tabs_http import close_tab, get_new_tab_url, list_tabs
from arena.browser.cdp_client.websocket_adapter import WebsocketsCDPAdapter

class CDPTabManagerTabLookupMixin:
    def get_tab(self, target_id: str) -> Optional[CDPTab]:
        """Get a CDPTab by target ID."""
        return self._tabs.get(target_id)

    def get_tab_by_url(self, url: str) -> Optional[CDPTab]:
        """Find a tab by its URL (exact match)."""
        for tab in self._tabs.values():
            if tab.url == url:
                return tab
        return None

    def get_tab_by_title(self, title: str) -> Optional[CDPTab]:
        """Find a tab by its title (exact match)."""
        for tab in self._tabs.values():
            if tab.title == title:
                return tab
        return None

    def list_tabs(self) -> List[CDPTab]:
        """List all tracked tabs."""
        return list(self._tabs.values())

    async def connect_tab(self, target_id: str) -> CDPTab:
        """Connect to a tracked tab that isn't connected yet.

        Useful when auto_discover_existing=False or for reconnecting.

        Args:
            target_id: The target ID of the tab

        Returns:
            The connected CDPTab

        Raises:
            KeyError: if target_id is not tracked
            ConnectionError: if connection fails
        """
        tab = self._tabs.get(target_id)
        if tab is None:
            raise KeyError(f"Tab {target_id} is not tracked")
        if not tab.connected:
            await asyncio.wait_for(tab.connect(), timeout=self.timeout)
        return tab

    async def disconnect_tab(self, target_id: str) -> None:
        """Disconnect from a tab without closing it in the browser.

        Args:
            target_id: The target ID of the tab
        """
        tab = self._tabs.get(target_id)
        if tab and tab.connected:
            await tab.disconnect()

    async def sync_tabs(self) -> List[CDPTab]:
        """Synchronize tracked tabs with the browser's actual tab list.

        Discovers new tabs, removes closed ones. Useful if the
        browser-level WebSocket is unavailable and tab events were missed.

        Returns:
            Updated list of all tracked tabs
        """
        loop = asyncio.get_running_loop()
        current_tabs = await loop.run_in_executor(None, list_tabs, self.port)
        current_ids = set()

        for tab_info in current_tabs:
            if tab_info.get("type") != "page":
                continue
            target_id = tab_info.get("id", "")
            ws_url = tab_info.get("webSocketDebuggerUrl", "")
            if not target_id:
                continue

            current_ids.add(target_id)

            if target_id in self._tabs:
                # Update existing tab metadata
                tab = self._tabs[target_id]
                tab.title = tab_info.get("title", tab.title)
                tab.url = tab_info.get("url", tab.url)
                if ws_url:
                    tab.ws_url = ws_url
            else:
                # New tab discovered
                if not ws_url:
                    continue
                tab = CDPTab(
                    target_id=target_id,
                    ws_url=ws_url,
                    port=self.port,
                    timeout=self.timeout,
                    title=tab_info.get("title", ""),
                    url=tab_info.get("url", ""),
                )
                self._tabs[target_id] = tab

        # Remove tabs that no longer exist
        removed_ids = set(self._tabs.keys()) - current_ids
        for target_id in removed_ids:
            tab = self._tabs.pop(target_id)
            if tab.connected:
                await tab.disconnect()
            if self._active_tab_id == target_id:
                self._active_tab_id = next(iter(self._tabs)) if self._tabs else None

        if removed_ids:
            logger.info("[CDPTabManager] Sync removed %d stale tab(s)", len(removed_ids))

        return self.list_tabs()
