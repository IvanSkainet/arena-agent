"""CDP tab manager component."""
from __future__ import annotations

from arena.browser.cdp_client.common import *  # noqa: F401,F403
from arena.browser.cdp_client.process import launch_browser
from arena.browser.cdp_client.tab import CDPTab
from arena.browser.cdp_client.tabs_http import close_tab, get_new_tab_url, list_tabs
from arena.browser.cdp_client.websocket_adapter import WebsocketsCDPAdapter

class CDPTabManagerTargetMixin:
    async def _handle_target_created(self, params: Dict) -> None:
        """Handle Target.targetCreated event."""
        target_info = params.get("targetInfo", {})
        target_id = target_info.get("targetId", "")
        target_type = target_info.get("type", "")

        # Only track page targets (tabs)
        if target_type != "page":
            return

        if target_id in self._tabs:
            return  # Already tracked

        # Get the WebSocket URL for this new tab
        ws_url = await self._get_ws_url_for_target(target_id)
        if not ws_url:
            # Fallback: try from tab list (non-blocking)
            loop = asyncio.get_running_loop()
            tabs = await loop.run_in_executor(None, list_tabs, self.port)
            for tab_info in tabs:
                if tab_info.get("id") == target_id:
                    ws_url = tab_info.get("webSocketDebuggerUrl", "")
                    break

        if not ws_url:
            logger.warning("[CDPTabManager] No WS URL for new target %s", target_id)
            return

        tab = CDPTab(
            target_id=target_id,
            ws_url=ws_url,
            port=self.port,
            timeout=self.timeout,
            title=target_info.get("title", ""),
            url=target_info.get("url", ""),
        )
        self._tabs[target_id] = tab

        # Set as active if this is the first tab
        if self._active_tab_id is None:
            self._active_tab_id = target_id

        logger.info("[CDPTabManager] Tab created: %s (%s)", target_id, tab.title or tab.url)

        # Fire callbacks
        for cb in self._tab_created_callbacks:
            try:
                result = cb({"tab": tab, "event": "created", "info": target_info})
                if asyncio.iscoroutine(result):
                    task = asyncio.create_task(result)
                    task.add_done_callback(self._log_callback_error)
                    self._callback_tasks.append(task)
            except Exception as e:
                logger.error("[CDPTabManager] tab_created callback error: %s", e)

    async def _handle_target_destroyed(self, params: Dict) -> None:
        """Handle Target.targetDestroyed event."""
        target_id = params.get("targetId", "")

        tab = self._tabs.pop(target_id, None)
        if tab is None:
            return

        # Disconnect the tab's CDP connection
        if tab.connected:
            await tab.disconnect()

        # Update active tab if needed
        if self._active_tab_id == target_id:
            self._active_tab_id = None
            # Activate another tab if available
            if self._tabs:
                self._active_tab_id = next(iter(self._tabs))

        logger.info("[CDPTabManager] Tab destroyed: %s", target_id)

        # Fire callbacks
        for cb in self._tab_destroyed_callbacks:
            try:
                result = cb({"tab": tab, "event": "destroyed", "info": {"targetId": target_id}})
                if asyncio.iscoroutine(result):
                    task = asyncio.create_task(result)
                    task.add_done_callback(self._log_callback_error)
                    self._callback_tasks.append(task)
            except Exception as e:
                logger.error("[CDPTabManager] tab_destroyed callback error: %s", e)

    async def _handle_target_info_changed(self, params: Dict) -> None:
        """Handle Target.targetInfoChanged event."""
        target_info = params.get("targetInfo", {})
        target_id = target_info.get("targetId", "")

        tab = self._tabs.get(target_id)
        if tab is None:
            return

        old_url = tab.url
        tab.title = target_info.get("title", tab.title)
        tab.url = target_info.get("url", tab.url)

        # Fire navigated callback if URL changed
        if old_url != tab.url:
            for cb in self._tab_navigated_callbacks:
                try:
                    result = cb({
                        "tab": tab,
                        "event": "navigated",
                        "info": {"old_url": old_url, "new_url": tab.url},
                    })
                    if asyncio.iscoroutine(result):
                        task = asyncio.create_task(result)
                        task.add_done_callback(self._log_callback_error)
                        self._callback_tasks.append(task)
                except Exception as e:
                    logger.error("[CDPTabManager] tab_navigated callback error: %s", e)

    async def _get_ws_url_for_target(self, target_id: str) -> Optional[str]:
        """Get the WebSocket URL for a target ID.

        Uses Target.getTargetInfo (non-session-creating) to verify the target
        exists, then constructs the WS URL. Falls back to HTTP /json/list.
        """
        # Try via CDP Target.getTargetInfo (does NOT create a session)
        if self._browser_ws and not self._browser_ws.closed:
            try:
                res = await self._browser_send(
                    "Target.getTargetInfo",
                    {"targetId": target_id},
                )
                if res and "result" in res:
                    # Target confirmed to exist — construct WS URL
                    return f"ws://127.0.0.1:{self.port}/devtools/page/{target_id}"
            except Exception:
                pass

        # Fallback: search in HTTP tab list
        loop = asyncio.get_running_loop()
        tabs = await loop.run_in_executor(None, list_tabs, self.port)
        for tab_info in tabs:
            if tab_info.get("id") == target_id:
                return tab_info.get("webSocketDebuggerUrl")

        return None
