"""Active-tab connection fallbacks for CDPTabManager.connect()."""
from __future__ import annotations

from arena.browser.cdp_client.browser import CDPBrowser
from arena.browser.cdp_client.common import *  # noqa: F401,F403
from arena.browser.cdp_client.websocket_adapter import WebsocketsCDPAdapter


class CDPTabManagerActiveConnectMixin:
    async def _wire_direct_browser(self, active_tab, ws, session, lib_name: str) -> bool:
        browser_inst = CDPBrowser(port=self.port, auto_launch=False, timeout=self.timeout)
        browser_inst._ws = WebsocketsCDPAdapter(ws) if lib_name == "websockets" else ws
        browser_inst._session = session
        browser_inst._closing = True
        browser_inst._listener_task = asyncio.create_task(browser_inst._listen_loop())
        try:
            await browser_inst.send("Page.enable")
            await browser_inst.send("Runtime.enable")
        except Exception as e:
            logger.warning("[CDPManager] CDP domain enable failed (non-fatal): %s", e)
        active_tab._browser = browser_inst
        active_tab._connected = True
        logger.info("[CDPManager] Tab %s CONNECTED via direct %s fallback!", active_tab.target_id, lib_name)
        return True

    async def _direct_websockets_fallback(self, active_tab) -> bool:
        if not HAS_WEBSOCKETS:
            return False
        try:
            ws = await asyncio.wait_for(
                _websockets_mod.connect(active_tab.ws_url, open_timeout=5, close_timeout=3),
                timeout=7,
            )
            self.ws_diagnostics.update({"direct_fallback_ok": True, "direct_fallback_lib": "websockets"})
            return await self._wire_direct_browser(active_tab, ws, None, "websockets")
        except asyncio.TimeoutError:
            self.ws_diagnostics.update({"direct_fallback_ok": False, "direct_fallback_error": "TIMEOUT (7s)"})
            logger.warning("[CDPManager] Direct websockets fallback TIMED OUT (7s)")
        except Exception as e:
            self.ws_diagnostics.update({"direct_fallback_ok": False, "direct_fallback_error": f"{type(e).__name__}: {e}"})
            logger.warning("[CDPManager] Direct websockets fallback FAILED: %s\n%s", e, traceback.format_exc())
        return False

    async def _direct_aiohttp_fallback(self, active_tab) -> bool:
        logger.info("[CDPManager] Trying direct aiohttp fallback to %s", active_tab.ws_url[:60])
        aiohttp_session = None
        try:
            ws_timeout = aiohttp.ClientTimeout(total=5, connect=3, sock_connect=3)
            connector = aiohttp.TCPConnector(force_close=True, enable_cleanup_closed=True)
            aiohttp_session = aiohttp.ClientSession(timeout=ws_timeout, connector=connector)
            ws = await asyncio.wait_for(aiohttp_session.ws_connect(active_tab.ws_url, heartbeat=None, proxy=None), timeout=7)
            self.ws_diagnostics.update({"direct_aiohttp_fallback_ok": True, "direct_fallback_lib": "aiohttp"})
            return await self._wire_direct_browser(active_tab, ws, aiohttp_session, "aiohttp")
        except asyncio.TimeoutError:
            self.ws_diagnostics.update({"direct_aiohttp_fallback_ok": False, "direct_aiohttp_fallback_error": "TIMEOUT (7s)"})
            logger.warning("[CDPManager] Direct aiohttp fallback TIMED OUT (7s)")
        except Exception as e:
            self.ws_diagnostics.update({"direct_aiohttp_fallback_ok": False, "direct_aiohttp_fallback_error": f"{type(e).__name__}: {e}"})
            logger.warning("[CDPManager] Direct aiohttp fallback FAILED: %s", e)
        if aiohttp_session and not aiohttp_session.closed:
            try:
                await aiohttp_session.close()
            except Exception:
                pass
        return False

    async def _auto_connect_active_tab(self, t0: float) -> bool:
        if not self._active_tab_id or self._active_tab_id not in self._tabs:
            self.ws_diagnostics["tab_ws_connected"] = False
            return False
        active_tab = self._tabs[self._active_tab_id]
        logger.info("[CDPManager] Auto-connecting to active tab %s (%.1fs)... ws_url=%s",
                    self._active_tab_id, time.monotonic() - t0, active_tab.ws_url[:60])
        try:
            await asyncio.wait_for(active_tab.connect(), timeout=25)
            logger.info("[CDPTabManager] Auto-connected to active tab %s (%.1fs)", self._active_tab_id, time.monotonic() - t0)
            return active_tab.connected
        except asyncio.TimeoutError:
            self.ws_diagnostics["tab_ws_error"] = f"TIMEOUT (25s). WS URL: {active_tab.ws_url}"
            logger.error("[CDPTabManager] Auto-connect to active tab %s TIMED OUT (25s)!", self._active_tab_id)
        except Exception as e:
            self.ws_diagnostics["tab_ws_error"] = f"{type(e).__name__}: {e}"
            logger.warning("[CDPTabManager] Failed to auto-connect active tab: %s\n%s", e, traceback.format_exc())

        if not active_tab.ws_url:
            return False
        self.ws_diagnostics["direct_fallback_url"] = active_tab.ws_url
        return await self._direct_websockets_fallback(active_tab) or await self._direct_aiohttp_fallback(active_tab)
