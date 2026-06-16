"""Top-level CDPTabManager.connect() orchestration."""
from __future__ import annotations

from arena.browser.cdp_client.common import *  # noqa: F401,F403
from arena.browser.cdp_client.tab_manager_connect_active import CDPTabManagerActiveConnectMixin
from arena.browser.cdp_client.tab_manager_connect_launch import CDPTabManagerConnectLaunchMixin


class CDPTabManagerConnectMixin(CDPTabManagerConnectLaunchMixin, CDPTabManagerActiveConnectMixin):
    async def connect(self) -> None:
        """Connect to the browser and discover existing tabs."""
        if not HAS_AIOHTTP:
            raise RuntimeError("aiohttp is required for CDPTabManager. Install with: pip install aiohttp")

        t0 = time.monotonic()
        logger.info("[CDPManager] connect() START port=%d", self.port)
        loop = asyncio.get_running_loop()

        await self._kill_stale_port_processes(loop)
        existing_tabs = await self._list_tabs_safe(loop)
        self._record_existing_tab_diagnostics(existing_tabs, t0)
        existing_tabs = await self._launch_if_needed(existing_tabs, loop, t0)

        await self._connect_browser_level_events(t0)
        self._register_existing_tabs(existing_tabs)
        await self._auto_connect_active_tab(t0)

        logger.info(
            "[CDPTabManager] Connected. Tracking %d tab(s), active: %s (%.1fs)",
            len(self._tabs),
            self._active_tab_id or "none",
            time.monotonic() - t0,
        )
