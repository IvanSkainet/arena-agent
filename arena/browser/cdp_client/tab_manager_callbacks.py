"""CDP tab manager component."""
from __future__ import annotations

from cdp_browser_modules.common import *  # noqa: F401,F403
from cdp_browser_modules.process import launch_browser
from cdp_browser_modules.tab import CDPTab
from cdp_browser_modules.tabs_http import close_tab, get_new_tab_url, list_tabs
from cdp_browser_modules.websocket_adapter import WebsocketsCDPAdapter

class CDPTabManagerCallbackMixin:
    def on_tab_created(self, callback: Callable) -> None:
        """Register a callback for tab creation events.

        Callback receives: {"tab": CDPTab, "event": "created", "info": dict}
        """
        self._tab_created_callbacks.append(callback)

    def on_tab_destroyed(self, callback: Callable) -> None:
        """Register a callback for tab destruction events.

        Callback receives: {"tab": CDPTab, "event": "destroyed", "info": dict}
        """
        self._tab_destroyed_callbacks.append(callback)

    def on_tab_navigated(self, callback: Callable) -> None:
        """Register a callback for tab navigation events.

        Callback receives: {"tab": CDPTab, "event": "navigated", "info": dict}
        """
        self._tab_navigated_callbacks.append(callback)

    def off_tab_created(self, callback: Callable) -> None:
        """Unregister a tab creation callback."""
        if callback in self._tab_created_callbacks:
            self._tab_created_callbacks.remove(callback)

    def off_tab_destroyed(self, callback: Callable) -> None:
        """Unregister a tab destruction callback."""
        if callback in self._tab_destroyed_callbacks:
            self._tab_destroyed_callbacks.remove(callback)

    def off_tab_navigated(self, callback: Callable) -> None:
        """Unregister a tab navigation callback."""
        if callback in self._tab_navigated_callbacks:
            self._tab_navigated_callbacks.remove(callback)

    def _log_callback_error(task: asyncio.Task) -> None:
        """Log exceptions from fire-and-forget callback tasks."""
        if not task.cancelled():
            try:
                task.exception()
            except Exception as e:
                logger.error("[CDPTabManager] Async callback task error: %s", e)

    async def close(self) -> None:
        """Close all tab connections and the browser-level WebSocket."""
        self._closing = True

        # Cancel pending browser-level futures so callers don't hang
        for msg_id, future in list(self._browser_pending.items()):
            if not future.done():
                future.cancel()
        self._browser_pending.clear()

        # Cancel orphaned callback tasks
        for task in self._callback_tasks:
            if not task.done():
                task.cancel()
        self._callback_tasks.clear()

        # Disconnect all tracked tabs
        for tab in list(self._tabs.values()):
            if tab.connected:
                try:
                    await tab.disconnect()
                except Exception as e:
                    logger.warning("[CDPTabManager] Error disconnecting tab %s: %s", tab.target_id, e)
        self._tabs.clear()

        # Close browser-level WebSocket
        if self._browser_listener_task:
            self._browser_listener_task.cancel()
            try:
                await self._browser_listener_task
            except asyncio.CancelledError:
                pass

        if self._browser_ws and not self._browser_ws.closed:
            await self._browser_ws.close()
        if self._browser_session and not self._browser_session.closed:
            await self._browser_session.close()

        # Terminate browser if we launched it
        if self._browser_proc:
            self._browser_proc.terminate()
            try:
                self._browser_proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._browser_proc.kill()

        logger.info("[CDPTabManager] Closed")

    def __repr__(self) -> str:
        return (
            f"CDPTabManager(port={self.port}, tabs={len(self._tabs)}, "
            f"active={self._active_tab_id!r})"
        )

    def to_dict(self) -> Dict[str, Any]:
        """Serialize manager state to a dict (for API responses)."""
        return {
            "port": self.port,
            "tab_count": len(self._tabs),
            "active_tab_id": self._active_tab_id,
            "tabs": [tab.to_dict() for tab in self._tabs.values()],
        }
