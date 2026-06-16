"""CDP tab manager component."""
from __future__ import annotations

from cdp_browser_modules.common import *  # noqa: F401,F403
from cdp_browser_modules.process import launch_browser
from cdp_browser_modules.tab import CDPTab
from cdp_browser_modules.tabs_http import close_tab, get_new_tab_url, list_tabs
from cdp_browser_modules.websocket_adapter import WebsocketsCDPAdapter

class CDPTabManagerBrowserWsMixin:
    async def _connect_browser_ws(self) -> None:
        """Connect to the browser-level WebSocket for Target domain events.

        Uses the /json/version endpoint to get the browser WebSocket URL,
        which allows monitoring all target (tab) lifecycle events.

        This is NON-FATAL — if the browser-level WS fails, we still connect
        to individual tabs. Tab lifecycle events will just be unavailable.

        v1.9.17: Falls back to websockets library if aiohttp ws_connect hangs,
        and constructs browser WS URL from /json/version id if
        webSocketDebuggerUrl is missing.
        """
        browser_ws_url = await self._get_browser_ws_url()
        if not browser_ws_url:
            logger.warning("[CDPTabManager] No browser-level WS URL from /json/version; tab events disabled")
            self.ws_diagnostics["browser_ws_error"] = "No browser WS URL from /json/version"
            return

        logger.info("[CDPTabManager] Browser WS URL: %s", browser_ws_url)

        # Strategy 1: aiohttp with force_close connector, no proxy, no heartbeat
        ws_connected = False
        try:
            ws_timeout = aiohttp.ClientTimeout(total=15, connect=10, sock_connect=10)
            connector = aiohttp.TCPConnector(force_close=True, enable_cleanup_closed=True)
            self._browser_session = aiohttp.ClientSession(timeout=ws_timeout, connector=connector)
            self._browser_ws = await asyncio.wait_for(
                self._browser_session.ws_connect(browser_ws_url, heartbeat=None, proxy=None),
                timeout=15
            )
            ws_connected = True
            logger.info("[CDPTabManager] Browser-level WS connected via aiohttp")
        except asyncio.TimeoutError:
            logger.warning("[CDPTabManager] Browser WS aioconnect TIMED OUT (15s)")
            if self._browser_session and not self._browser_session.closed:
                await self._browser_session.close()
            self._browser_session = None
            self._browser_ws = None
        except Exception as e:
            logger.warning("[CDPTabManager] Browser WS aiohttp FAILED: %s", e)
            if self._browser_session and not self._browser_session.closed:
                await self._browser_session.close()
            self._browser_session = None
            self._browser_ws = None

        # Strategy 2: websockets library as fallback
        if not ws_connected and HAS_WEBSOCKETS:
            try:
                logger.info("[CDPTabManager] Trying websockets library for browser WS...")
                ws_raw = await asyncio.wait_for(
                    _websockets_mod.connect(browser_ws_url, open_timeout=10, close_timeout=5),
                    timeout=12
                )
                self._browser_ws = WebsocketsCDPAdapter(ws_raw)
                self._browser_session = None  # No aiohttp session needed
                ws_connected = True
                logger.info("[CDPTabManager] Browser-level WS connected via websockets library")
            except asyncio.TimeoutError:
                logger.warning("[CDPTabManager] Browser WS websockets TIMED OUT (12s)")
                self._browser_ws = None
            except Exception as e:
                logger.warning("[CDPTabManager] Browser WS websockets FAILED: %s", e)
                self._browser_ws = None

        if not ws_connected:
            logger.warning("[CDPTabManager] Browser-level WS NOT connected (tab events disabled)")
            self.ws_diagnostics["browser_ws_error"] = f"All strategies failed. URL: {browser_ws_url}"
            return

        try:
            logger.info("[CDPTabManager] Browser-level WS connected, enabling Target domain...")

            # Start browser event listener FIRST — it must be running to process
            # the response from Target.setDiscoverTargets
            self._browser_listener_task = asyncio.create_task(self._browser_listen_loop())

            # Enable Target domain to receive tab lifecycle events
            await asyncio.wait_for(
                self._browser_send("Target.setDiscoverTargets", {"discover": True}),
                timeout=5
            )

            logger.info("[CDPTabManager] Browser-level WS connected for Target events")
        except Exception as e:
            logger.warning("[CDPTabManager] Target.setDiscoverTargets failed: %s", e)
            self.ws_diagnostics["browser_ws_error"] = f"Target domain failed: {e}"

    async def _get_browser_ws_url(self) -> Optional[str]:
        """Get the browser-level WebSocket URL from /json/version.

        v1.9.18: Logs full /json/version response for debugging.
        If webSocketDebuggerUrl is missing, tries multiple construction
        strategies including a blind fallback that tries /devtools/browser/
        without an id (works with some Chromium builds).
        """
        url = f"http://127.0.0.1:{self.port}/json/version"
        try:
            loop = asyncio.get_running_loop()
            def _fetch():
                with urllib.request.urlopen(url, timeout=5) as r:
                    return json.loads(r.read().decode())
            info = await loop.run_in_executor(None, _fetch)
            ws_url = info.get("webSocketDebuggerUrl")

            # v1.9.18: Log full /json/version response for diagnostics
            logger.info("[CDPManager] /json/version FULL response: %s",
                        json.dumps({k: str(v)[:80] for k, v in info.items()}))

            # If webSocketDebuggerUrl is missing, try to construct it
            if not ws_url:
                # Strategy A: Use 'id' field from /json/version
                browser_id = info.get("id") or info.get("browser-id")
                if browser_id:
                    ws_url = f"ws://127.0.0.1:{self.port}/devtools/browser/{browser_id}"
                    logger.info("[CDPManager] Constructed browser WS URL from id: %s", ws_url)
                    self.ws_diagnostics["browser_ws_url_source"] = "constructed_from_version_id"
                else:
                    # Strategy B: Look for browser-type target in /json/list
                    tabs = await loop.run_in_executor(None, list_tabs, self.port)
                    for tab in tabs:
                        if tab.get("type") == "browser" and tab.get("webSocketDebuggerUrl"):
                            ws_url = tab["webSocketDebuggerUrl"]
                            logger.info("[CDPManager] Found browser WS URL from /json/list: %s", ws_url[:60])
                            self.ws_diagnostics["browser_ws_url_source"] = "from_json_list_browser_target"
                            break
                    if not ws_url:
                        # Strategy C: Blind probe — just try connecting without an id
                        # Some Chromium builds accept connections on this path
                        logger.warning("[CDPManager] Cannot determine browser WS URL from /json/version or /json/list")
                        logger.info("[CDPManager] /json/version keys: %s", list(info.keys()))
                        self.ws_diagnostics["browser_ws_url_source"] = "unavailable"
                        self.ws_diagnostics["version_info_keys"] = list(info.keys())
            else:
                self.ws_diagnostics["browser_ws_url_source"] = "from_version_webSocketDebuggerUrl"

            return ws_url
        except Exception as e:
            logger.warning("[CDPManager] Failed to fetch /json/version: %s", e)
            return None

    async def _browser_send(self, method: str, params: Optional[Dict] = None,
                            timeout: Optional[float] = None) -> Dict:
        """Send a CDP command on the browser-level WebSocket."""
        if not self._browser_ws or self._browser_ws.closed:
            raise ConnectionError("Browser WebSocket is not connected")

        msg_id = next(self._browser_req_id)
        msg = {"id": msg_id, "method": method}
        if params:
            msg["params"] = params

        loop = asyncio.get_running_loop()
        future = loop.create_future()
        self._browser_pending[msg_id] = future

        await self._browser_ws.send_json(msg)
        logger.debug("[CDPTabManager:BrowserWS] -> %s %s (id=%d)", method, params or "", msg_id)

        effective_timeout = timeout or self.timeout
        try:
            return await asyncio.wait_for(future, effective_timeout)
        except asyncio.TimeoutError:
            self._browser_pending.pop(msg_id, None)
            raise

    async def _browser_listen_loop(self) -> None:
        """Background task: listen for browser-level CDP events (Target.*)."""
        # Same type handling as _listen_loop for WebsocketsCDPAdapter compatibility
        TEXT_TYPE = aiohttp.WSMsgType.TEXT if HAS_AIOHTTP else 1
        CLOSED_TYPES = set()
        if HAS_AIOHTTP:
            CLOSED_TYPES.add(aiohttp.WSMsgType.CLOSED)
            CLOSED_TYPES.add(aiohttp.WSMsgType.ERROR)
        CLOSED_TYPES.add(0x100)  # WebsocketsCDPAdapter sentinel
        CLOSED_TYPES.add(-1)

        try:
            async for msg in self._browser_ws:
                if msg.type == TEXT_TYPE:
                    try:
                        data = json.loads(msg.data)
                    except json.JSONDecodeError:
                        continue

                    # Handle responses to our browser-level commands
                    msg_id = data.get("id")
                    if msg_id and msg_id in self._browser_pending:
                        future = self._browser_pending.pop(msg_id)
                        if not future.done():
                            future.set_result(data)
                        continue

                    # Handle Target domain events
                    method = data.get("method", "")
                    params = data.get("params", {})

                    if method == "Target.targetCreated":
                        await self._handle_target_created(params)
                    elif method == "Target.targetDestroyed":
                        await self._handle_target_destroyed(params)
                    elif method == "Target.targetInfoChanged":
                        await self._handle_target_info_changed(params)

                elif msg.type in CLOSED_TYPES:
                    break
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error("[CDPTabManager:BrowserWS] Listener error: %s", e)
