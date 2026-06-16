"""
Chrome DevTools Protocol (CDP) browser controller.

Async-first design using aiohttp for WebSocket communication.
Falls back to synchronous CLI when run as __main__.

Features:
  - Incremental request IDs (no collisions)
  - Event system with callbacks and event queue
  - Page load detection via Page.loadEventFired (no blind sleep)
  - Timeouts on all operations via asyncio.wait_for
  - Auto-reconnect on WebSocket drop
  - Multi-tab awareness (list tabs, connect to specific tab)
  - Full multi-tab management via CDPTabManager + CDPTab
  - Tab lifecycle events (created, destroyed, navigated)
  - Per-tab event isolation with independent WebSocket connections
  - Context manager: async with CDPBrowser() as browser

CLI (backward-compatible):
  python3 cdp_browser.py navigate <url>
  python3 cdp_browser.py shot [png_path]
  python3 cdp_browser.py dump
  python3 cdp_browser.py eval <js>
  python3 cdp_browser.py tabs
  python3 cdp_browser.py multitab          # Interactive multi-tab demo
"""

import sys
import os
import base64
import json
import urllib.request
import subprocess
import time
import platform
import shutil
import traceback
import tempfile
import asyncio
import itertools
import logging
from typing import Optional, Callable, Any, Dict, List

# ---------------------------------------------------------------------------
# Optional aiohttp import — graceful degradation for environments without it
# ---------------------------------------------------------------------------
try:
    import aiohttp
    HAS_AIOHTTP = True
except ImportError:
    HAS_AIOHTTP = False

try:
    import websockets as _websockets_mod
    HAS_WEBSOCKETS = True
except ImportError:
    HAS_WEBSOCKETS = False

logger = logging.getLogger("cdp_browser")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
DEFAULT_PORT = 9222
DEFAULT_TIMEOUT = 30  # seconds
RECONNECT_ATTEMPTS = 3
RECONNECT_DELAY = 1  # seconds

from cdp_browser_modules.process import (
    find_browser_exe, _resolve_browser_binary, _build_session_env, _build_chromium_cmd,
    _ts, _drain_stderr, _kill_port_processes, _write_diag_file, launch_browser,
)
from cdp_browser_modules.tabs_http import list_tabs, get_websocket_url, get_new_tab_url, close_tab
from cdp_browser_modules.websocket_adapter import WebsocketsCDPAdapter, _WSMessage
from cdp_browser_modules.sync_browser import SyncCDPBrowser
from cdp_browser_modules.network_monitor import NetworkRequest, CDPNetworkMonitor
from cdp_browser_modules.interceptor import InterceptRule, CDPNetworkInterceptor
from cdp_browser_modules.cookies import CDPCookieManager


# ---------------------------------------------------------------------------
# Browser process management
# ---------------------------------------------------------------------------


















# ---------------------------------------------------------------------------
# HTTP helpers (no aiohttp needed)
# ---------------------------------------------------------------------------








# ---------------------------------------------------------------------------
# WebsocketsCDPAdapter — wraps websockets library for CDPBrowser
# ---------------------------------------------------------------------------





# ---------------------------------------------------------------------------
# Async CDP Browser class
# ---------------------------------------------------------------------------
class CDPBrowser:
    """Async Chrome DevTools Protocol browser controller.

    Usage:
        async with CDPBrowser() as browser:
            await browser.navigate("https://example.com")
            await browser.screenshot("out.png")
            html = await browser.dump_dom()
            result = await browser.eval_js("1 + 2")
    """

    def __init__(
        self,
        port: int = DEFAULT_PORT,
        headless: bool = True,
        auto_launch: bool = True,
        timeout: float = DEFAULT_TIMEOUT,
        tab_index: int = 0,
    ):
        self.port = port
        self.headless = headless
        self.auto_launch = auto_launch
        self.timeout = timeout
        self.tab_index = tab_index

        self._ws: Optional[aiohttp.ClientWebSocketResponse] = None
        self._session: Optional[aiohttp.ClientSession] = None
        self._req_id = itertools.count(1)
        self._pending: Dict[int, asyncio.Future] = {}
        self._event_handlers: Dict[str, List[Callable]] = {}
        self._listener_task: Optional[asyncio.Task] = None
        self._browser_proc: Optional[subprocess.Popen] = None
        self._closing = False
        self._reconnecting = False

    # -- Context manager ---------------------------------------------------

    async def __aenter__(self):
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()

    # -- Connection management ---------------------------------------------

    async def connect(self) -> None:
        """Connect to the browser's CDP WebSocket endpoint."""
        if not HAS_AIOHTTP:
            raise RuntimeError("aiohttp is required for async CDP. Install with: pip install aiohttp")

        ws_url = get_websocket_url(self.port, self.tab_index)

        if ws_url is None and self.auto_launch:
            loop = asyncio.get_running_loop()
            self._browser_proc = await loop.run_in_executor(
                None, launch_browser, self.port, self.headless)
            # Check if browser process died immediately
            if self._browser_proc and self._browser_proc.poll() is not None:
                launch_diag = getattr(self._browser_proc, '_cdp_launch_diag', {})
                raise ConnectionError(
                    f"Browser process exited immediately (rc={self._browser_proc.returncode}). "
                    f"Launch diag: {launch_diag}"
                )
            # Retry until the debug port is ready (up to 15 seconds)
            for _ in range(15):
                ws_url = get_websocket_url(self.port, self.tab_index)
                if ws_url:
                    break
                # Check if browser crashed
                if self._browser_proc and self._browser_proc.poll() is not None:
                    launch_diag = getattr(self._browser_proc, '_cdp_launch_diag', {})
                    raise ConnectionError(
                        f"Browser crashed during startup (rc={self._browser_proc.returncode}). "
                        f"Launch diag: {launch_diag}"
                    )
                await asyncio.sleep(1)

        if ws_url is None:
            raise ConnectionError(f"Cannot connect to browser CDP on port {self.port}")

        self._session = aiohttp.ClientSession()
        try:
            self._ws = await self._session.ws_connect(ws_url, heartbeat=30)
        except Exception:
            await self._session.close()
            raise

        # Start the WebSocket listener FIRST — it must be running to process
        # responses from Page.enable/Runtime.enable. Without this, send()
        # hangs indefinitely waiting for a response that nobody reads.
        self._listener_task = asyncio.create_task(self._listen_loop())

        # Enable core domains (listener is now running to process responses)
        await self.send("Page.enable")
        await self.send("Runtime.enable")

        logger.info("[CDP] Connected to %s", ws_url)

    async def close(self) -> None:
        """Close the WebSocket connection and clean up."""
        self._closing = True

        # Cancel pending futures so callers don't hang
        for msg_id, future in list(self._pending.items()):
            if not future.done():
                future.cancel()
        self._pending.clear()

        # Only cancel listener if we're not inside it (avoid deadlock)
        if self._listener_task and not self._reconnecting:
            self._listener_task.cancel()
            try:
                await self._listener_task
            except asyncio.CancelledError:
                pass

        if self._ws and not self._ws.closed:
            await self._ws.close()

        # _session may be None when using WebsocketsCDPAdapter (Strategy 3)
        if self._session is not None and not self._session.closed:
            await self._session.close()

        if self._browser_proc:
            self._browser_proc.terminate()
            try:
                self._browser_proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._browser_proc.kill()

        self._listener_task = None
        logger.info("[CDP] Connection closed")

    async def reconnect(self) -> None:
        """Attempt to reconnect after a connection drop.

        Called from within _listen_loop, so we must avoid the deadlock
        where close() tries to await the listener task (itself).
        """
        self._reconnecting = True
        self._closing = True

        # Cancel pending futures
        for msg_id, future in list(self._pending.items()):
            if not future.done():
                future.cancel()
        self._pending.clear()

        # Close WS and session without cancelling the listener task
        if self._ws and not self._ws.closed:
            await self._ws.close()
        # _session may be None when using WebsocketsCDPAdapter
        if self._session is not None and not self._session.closed:
            await self._session.close()

        self._closing = False
        self._reconnecting = False

        for attempt in range(1, RECONNECT_ATTEMPTS + 1):
            logger.info("[CDP] Reconnect attempt %d/%d", attempt, RECONNECT_ATTEMPTS)
            try:
                await self.connect()
                return
            except Exception as e:
                logger.warning("[CDP] Reconnect failed: %s", e)
                await asyncio.sleep(RECONNECT_DELAY)
        raise ConnectionError("Failed to reconnect after all attempts")

    # -- Low-level CDP communication ---------------------------------------

    async def send(self, method: str, params: Optional[Dict] = None,
                   timeout: Optional[float] = None) -> Dict:
        """Send a CDP command and wait for its response.

        Args:
            method: CDP method name (e.g., "Page.navigate")
            params: Optional parameters dict
            timeout: Override default timeout for this call

        Returns:
            The CDP response dict (with "id" and "result" or "error")

        Raises:
            asyncio.TimeoutError: if the response doesn't arrive in time
            ConnectionError: if the WebSocket is closed
        """
        if not self._ws or self._ws.closed:
            raise ConnectionError("WebSocket is not connected")

        msg_id = next(self._req_id)
        msg = {"id": msg_id, "method": method}
        if params:
            msg["params"] = params

        loop = asyncio.get_running_loop()
        future = loop.create_future()
        self._pending[msg_id] = future

        await self._ws.send_json(msg)
        logger.debug("[CDP] -> %s %s (id=%d)", method, params or "", msg_id)

        effective_timeout = timeout or self.timeout
        try:
            result = await asyncio.wait_for(future, effective_timeout)
            if "error" in result:
                logger.warning("[CDP] Error response for %s: %s", method, result["error"])
            return result
        except asyncio.TimeoutError:
            self._pending.pop(msg_id, None)
            raise
        except Exception:
            self._pending.pop(msg_id, None)
            raise

    # -- Event system ------------------------------------------------------

    def on(self, event_name: str, callback: Callable[[Dict], Any]) -> None:
        """Register a callback for a CDP event.

        Args:
            event_name: CDP event name (e.g., "Page.loadEventFired")
            callback: Function to call with the event params dict
        """
        self._event_handlers.setdefault(event_name, []).append(callback)

    def off(self, event_name: str, callback: Callable) -> None:
        """Unregister a callback for a CDP event."""
        handlers = self._event_handlers.get(event_name, [])
        if callback in handlers:
            handlers.remove(callback)

    async def wait_for_event(self, event_name: str, timeout: Optional[float] = None) -> Dict:
        """Wait for a specific CDP event and return its params.

        This is a convenience method that creates a one-shot listener.
        """
        effective_timeout = timeout or self.timeout
        loop = asyncio.get_running_loop()
        future = loop.create_future()

        def one_shot(params: Dict):
            if not future.done():
                future.set_result(params)

        self.on(event_name, one_shot)
        try:
            return await asyncio.wait_for(future, effective_timeout)
        finally:
            self.off(event_name, one_shot)

    # -- WebSocket listener ------------------------------------------------

    async def _listen_loop(self) -> None:
        """Background task that reads WebSocket messages and dispatches them."""
        # Determine TEXT/CLOSED/ERROR type constants based on WS implementation
        # (WebsocketsCDPAdapter returns _WSMessage with our sentinel values)
        TEXT_TYPE = aiohttp.WSMsgType.TEXT if HAS_AIOHTTP else 1
        CLOSED_TYPES = set()
        if HAS_AIOHTTP:
            CLOSED_TYPES.add(aiohttp.WSMsgType.CLOSED)
            CLOSED_TYPES.add(aiohttp.WSMsgType.ERROR)
        CLOSED_TYPES.add(0x100)  # Our WebsocketsCDPAdapter sentinel
        CLOSED_TYPES.add(-1)    # Fallback sentinel

        try:
            async for msg in self._ws:
                if msg.type == TEXT_TYPE:
                    try:
                        data = json.loads(msg.data)
                    except json.JSONDecodeError:
                        continue

                    # Dispatch response to pending future
                    msg_id = data.get("id")
                    if msg_id and msg_id in self._pending:
                        future = self._pending.pop(msg_id)
                        if not future.done():
                            future.set_result(data)
                        continue

                    # Dispatch event to handlers
                    method = data.get("method")
                    if method:
                        params = data.get("params", {})
                        # Call registered handlers
                        for handler in self._event_handlers.get(method, []):
                            try:
                                result = handler(params)
                                if asyncio.iscoroutine(result):
                                    asyncio.create_task(result)
                            except Exception as e:
                                logger.error("[CDP] Event handler error for %s: %s", method, e)

                elif msg.type in CLOSED_TYPES:
                    logger.warning("[CDP] WebSocket closed/error")
                    break
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error("[CDP] Listener error: %s", e)

        # If we got here unexpectedly, try reconnect
        if not self._closing:
            logger.info("[CDP] Connection lost, attempting reconnect...")
            try:
                await self.reconnect()
            except ConnectionError:
                logger.error("[CDP] Reconnect failed")

    # -- High-level convenience methods ------------------------------------

    async def navigate(self, url: str, wait: bool = True,
                       timeout: Optional[float] = None) -> Dict:
        """Navigate to a URL. Optionally wait for the page to fully load.

        Args:
            url: The URL to navigate to
            wait: If True, wait for Page.loadEventFired
            timeout: Override default timeout

        Returns:
            The Page.navigate response
        """
        effective_timeout = timeout or self.timeout

        if wait:
            # Set up load listener before navigating
            load_future = asyncio.ensure_future(
                self.wait_for_event("Page.loadEventFired", effective_timeout + 10)
            )
            try:
                result = await self.send("Page.navigate", {"url": url}, effective_timeout)
                await load_future  # Wait for page to actually load
                return result
            except asyncio.TimeoutError:
                load_future.cancel()
                raise
        else:
            return await self.send("Page.navigate", {"url": url}, effective_timeout)

    async def screenshot(self, path: Optional[str] = None,
                         timeout: Optional[float] = None) -> Optional[bytes]:
        """Capture a screenshot of the current page.

        Args:
            path: If provided, save PNG to this path
            timeout: Override default timeout

        Returns:
            Raw PNG bytes, or None on failure
        """
        res = await self.send("Page.captureScreenshot", timeout=timeout)
        if res and "result" in res and "data" in res["result"]:
            img_bytes = base64.b64decode(res["result"]["data"])
            if path:
                with open(path, "wb") as f:
                    f.write(img_bytes)
                logger.info("[CDP] Screenshot saved to %s (%d bytes)", path, len(img_bytes))
            return img_bytes
        return None

    async def dump_dom(self, timeout: Optional[float] = None) -> Optional[str]:
        """Dump the outerHTML of the current page.

        Returns:
            The HTML string, or None on failure
        """
        res = await self.send(
            "Runtime.evaluate",
            {"expression": "document.documentElement.outerHTML"},
            timeout=timeout,
        )
        if res and "result" in res and "result" in res["result"]:
            return res["result"]["result"].get("value")
        return None

    async def eval_js(self, expression: str,
                      timeout: Optional[float] = None) -> Any:
        """Evaluate a JavaScript expression in the page context.

        Returns:
            The result value from the Runtime.evaluate response
        """
        res = await self.send(
            "Runtime.evaluate",
            {"expression": expression, "returnByValue": True},
            timeout=timeout,
        )
        if res and "result" in res and "result" in res["result"]:
            return res["result"]["result"].get("value")
        return None

    async def get_tabs(self) -> List[Dict[str, Any]]:
        """List all open browser tabs."""
        return list_tabs(self.port)

    async def new_tab(self, url: str = "about:blank") -> Optional[str]:
        """Open a new browser tab and optionally navigate to a URL.

        Note: Navigation of the new tab requires a separate CDP connection
        to that tab's WebSocket URL. This method only creates the tab.
        Use navigate() on a CDPBrowser connected to the new tab to navigate it.

        Returns:
            The WebSocket URL of the new tab, or None on failure
        """
        ws_url = get_new_tab_url(self.port)
        return ws_url

    async def close_tab_by_id(self, tab_id: str) -> bool:
        """Close a tab by its target ID."""
        return close_tab(tab_id, self.port)

    async def get_cookies(self, timeout: Optional[float] = None) -> List[Dict]:
        """Get all cookies for the current page."""
        res = await self.send("Network.getCookies", timeout=timeout)
        if res and "result" in res:
            return res["result"].get("cookies", [])
        return []

    async def set_cookie(self, name: str, value: str, domain: str = "",
                         path: str = "/", timeout: Optional[float] = None) -> bool:
        """Set a cookie."""
        params = {"name": name, "value": value, "path": path}
        if domain:
            params["domain"] = domain
        res = await self.send("Network.setCookie", params, timeout=timeout)
        return res and res.get("result", {}).get("success", False)

    async def delete_cookie(self, name: str, domain: str = "",
                            timeout: Optional[float] = None) -> None:
        """Delete a cookie by name."""
        params = {"name": name}
        if domain:
            params["domain"] = domain
        await self.send("Network.deleteCookie", params, timeout=timeout)

    async def get_current_url(self, timeout: Optional[float] = None) -> Optional[str]:
        """Get the current page URL."""
        return await self.eval_js("window.location.href", timeout=timeout)

    async def get_title(self, timeout: Optional[float] = None) -> Optional[str]:
        """Get the current page title."""
        return await self.eval_js("document.title", timeout=timeout)

    async def click(self, selector: str, timeout: Optional[float] = None) -> bool:
        """Click an element matching a CSS selector.

        Uses JSON encoding to prevent JS injection via the selector string.
        Returns True if the element was found and clicked, False otherwise.
        """
        safe_selector = json.dumps(selector)  # JSON-encode to prevent injection
        expr = f'(function(){{var el=document.querySelector({safe_selector});if(el){{el.click();return true}}return false}})()'
        result = await self.eval_js(expr, timeout=timeout)
        return result is True

    async def click_at(self, x: float, y: float,
                       timeout: Optional[float] = None) -> bool:
        """Click at screen coordinates using CDP Input.dispatchMouseEvent.

        This can click inside iframes, cross-origin frames, and shadow DOM
        where CSS selectors cannot reach (e.g., reCAPTCHA checkbox).

        Args:
            x: X coordinate (CSS pixels from viewport origin)
            y: Y coordinate (CSS pixels from viewport origin)
            timeout: Override default timeout

        Returns:
            True if the CDP dispatch commands succeeded
        """
        try:
            # Move mouse to position
            await self.send("Input.dispatchMouseEvent", {
                "type": "mouseMoved",
                "x": x,
                "y": y,
            }, timeout=timeout)

            # Small delay to allow hover effects to settle
            await asyncio.sleep(0.05)

            # Mouse pressed
            await self.send("Input.dispatchMouseEvent", {
                "type": "mousePressed",
                "x": x,
                "y": y,
                "button": "left",
                "clickCount": 1,
            }, timeout=timeout)

            # Mouse released
            await self.send("Input.dispatchMouseEvent", {
                "type": "mouseReleased",
                "x": x,
                "y": y,
                "button": "left",
                "clickCount": 1,
            }, timeout=timeout)

            return True
        except Exception as e:
            logger.error("[CDP] click_at(%s, %s) failed: %s", x, y, e)
            return False

    async def type_text(self, selector: str, text: str,
                        timeout: Optional[float] = None) -> bool:
        """Type text into an element matching a CSS selector.

        Uses JSON encoding to prevent JS injection via selector and text strings.
        Returns True if the element was found and text was set, False otherwise.
        """
        safe_selector = json.dumps(selector)
        safe_text = json.dumps(text)
        expr = f'(function(){{var el=document.querySelector({safe_selector});if(el){{el.focus();el.value={safe_text};el.dispatchEvent(new Event("input",{{bubbles:true}}));return true}}return false}})()'
        result = await self.eval_js(expr, timeout=timeout)
        return result is True

    async def wait_for_selector(self, selector: str, poll_interval: float = 0.5,
                                timeout: Optional[float] = None) -> bool:
        """Wait until a CSS selector matches an element in the DOM.

        Uses JSON encoding to prevent JS injection via the selector string.
        Returns True if found within timeout, False otherwise.
        """
        effective_timeout = timeout or self.timeout
        loop = asyncio.get_running_loop()
        deadline = loop.time() + effective_timeout
        safe_selector = json.dumps(selector)
        expr = f'document.querySelector({safe_selector}) !== null'

        while loop.time() < deadline:
            result = await self.eval_js(expr, timeout=5)
            if result:
                return True
            await asyncio.sleep(poll_interval)
        return False


# ---------------------------------------------------------------------------
# Multi-tab management: CDPTab and CDPTabManager
# ---------------------------------------------------------------------------

class CDPTab:
    """Represents a single browser tab with its own CDP connection.

    Each CDPTab wraps a CDPBrowser instance connected to a specific tab's
    WebSocket URL, providing isolated operations and event handling.

    Usage:
        tab = CDPTab(target_id="ABC123", ws_url="ws://127.0.0.1:9222/devtools/page/ABC123")
        await tab.connect()
        await tab.navigate("https://example.com")
        title = await tab.get_title()
        await tab.close()
    """

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

    # -- Properties ----------------------------------------------------------

    @property
    def connected(self) -> bool:
        """Whether this tab has an active CDP connection."""
        return self._connected and self._browser is not None

    # -- Context manager -----------------------------------------------------

    async def __aenter__(self):
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.disconnect()

    # -- Connection management -----------------------------------------------

    async def connect(self) -> None:
        """Establish a CDP WebSocket connection to this tab.

        v1.9.19: Added traceback logging for every failed strategy.
        Reordered strategies — try websockets library FIRST since
        aiohttp ws_connect is known to hang on Python 3.14. Also reduced
        per-strategy timeouts to 5s to prevent total connect from taking
        more than 20s.
        """
        if self._connected and self._browser is not None:
            return

        if not HAS_AIOHTTP:
            raise RuntimeError("aiohttp is required for CDPTab. Install with: pip install aiohttp")

        logger.info("[CDPTab] Connecting to tab %s WS URL: %s", self.target_id, self.ws_url)

        # Create a CDPBrowser instance configured for this specific tab
        self._browser = CDPBrowser(
            port=self.port,
            auto_launch=False,  # Don't auto-launch — tab already exists
            timeout=self.timeout,
        )

        ws_connected = False
        last_error = None

        # v1.9.18: Strategy 1 — websockets library FIRST
        # On Python 3.14, aiohttp ws_connect is known to hang indefinitely
        # even with timeouts. The websockets library uses a completely
        # different implementation and is more reliable.
        if HAS_WEBSOCKETS:
            try:
                logger.info("[CDPTab] Strategy 1: websockets library (fastest, most reliable on Py3.14)")
                ws_raw = await asyncio.wait_for(
                    _websockets_mod.connect(self.ws_url, open_timeout=5, close_timeout=3),
                    timeout=7
                )
                logger.info("[CDPTab] Strategy 1 SUCCESS: websockets connected to %s", self.target_id)
                self._browser._ws = WebsocketsCDPAdapter(ws_raw)
                self._browser._session = None
                ws_connected = True
                logger.info("[CDPTab] Using websockets adapter for tab %s", self.target_id)
            except asyncio.TimeoutError:
                logger.warning("[CDPTab] Strategy 1 TIMED OUT (7s) — websockets library")
                last_error = f"websockets library timed out (7s). URL: {self.ws_url}"
            except ImportError:
                logger.info("[CDPTab] websockets library not available for Strategy 1")
                last_error = "websockets library not available"
            except Exception as e:
                logger.warning("[CDPTab] Strategy 1 FAILED: %s — websockets library\n%s", e, traceback.format_exc())
                last_error = f"websockets error: {type(e).__name__}: {e}. URL: {self.ws_url}"

        # Strategy 2: aiohttp with force_close connector, no proxy, NO heartbeat
        if not ws_connected:
            try:
                logger.info("[CDPTab] Strategy 2: aiohttp TCPConnector(force_close), no proxy, no heartbeat")
                ws_timeout = aiohttp.ClientTimeout(total=5, connect=3, sock_connect=3)
                connector = aiohttp.TCPConnector(force_close=True, enable_cleanup_closed=True)
                self._browser._session = aiohttp.ClientSession(
                    timeout=ws_timeout, connector=connector
                )
                self._browser._ws = await asyncio.wait_for(
                    self._browser._session.ws_connect(
                        self.ws_url, heartbeat=None,
                        proxy=None,
                    ),
                    timeout=5
                )
                ws_connected = True
                logger.info("[CDPTab] Strategy 2 SUCCESS: Tab %s WS connected", self.target_id)
            except asyncio.TimeoutError:
                logger.warning("[CDPTab] Strategy 2 TIMED OUT (5s) — URL: %s", self.ws_url)
                last_error = f"aiohttp ws_connect timed out (5s). URL: {self.ws_url}"
                if self._browser._session and not self._browser._session.closed:
                    await self._browser._session.close()
            except Exception as e:
                logger.warning("[CDPTab] Strategy 2 FAILED: %s — URL: %s\n%s", e, self.ws_url, traceback.format_exc())
                last_error = f"aiohttp ws_connect error: {type(e).__name__}: {e}. URL: {self.ws_url}"
                if self._browser._session and not self._browser._session.closed:
                    await self._browser._session.close()

        # Strategy 3: aiohttp default connector with heartbeat (last resort)
        if not ws_connected:
            try:
                logger.info("[CDPTab] Strategy 3: aiohttp with heartbeat=30")
                ws_timeout = aiohttp.ClientTimeout(total=8, connect=5, sock_connect=5)
                self._browser._session = aiohttp.ClientSession(timeout=ws_timeout)
                self._browser._ws = await asyncio.wait_for(
                    self._browser._session.ws_connect(self.ws_url, heartbeat=30, proxy=None),
                    timeout=8
                )
                ws_connected = True
                logger.info("[CDPTab] Strategy 3 SUCCESS: Tab %s WS connected", self.target_id)
            except asyncio.TimeoutError:
                logger.warning("[CDPTab] Strategy 3 TIMED OUT (8s)")
                last_error = f"aiohttp+heartbeat ws_connect timed out (8s). URL: {self.ws_url}"
                if self._browser._session and not self._browser._session.closed:
                    await self._browser._session.close()
            except Exception as e:
                logger.warning("[CDPTab] Strategy 3 FAILED: %s\n%s", e, traceback.format_exc())
                last_error = f"aiohttp+heartbeat error: {type(e).__name__}: {e}. URL: {self.ws_url}"
                if self._browser._session and not self._browser._session.closed:
                    await self._browser._session.close()

        # Strategy 4: websockets library if not tried yet
        if not ws_connected and not HAS_WEBSOCKETS:
            logger.info("[CDPTab] websockets library not available, all aiohttp strategies failed")
            last_error = f"All aiohttp strategies failed. websockets library not installed. {last_error}"

        if not ws_connected:
            self._browser = None
            raise ConnectionError(
                f"Tab {self.target_id} WebSocket connect FAILED after all strategies. "
                f"Last error: {last_error}. "
                f"HTTP works (list_tabs succeeds) but WebSocket upgrade fails. "
                f"This suggests a Chromium headless mode or aiohttp compatibility issue."
            )

        # Disable auto-reconnect: if WS drops, _listen_loop would call
        # reconnect() which connects to tab_index=0, NOT this tab.
        # Instead, let CDPTabManager handle reconnection at its level.
        self._browser._closing = True  # Prevents _listen_loop from calling reconnect

        # CRITICAL (v1.9.21): Start the listener loop BEFORE sending any CDP
        # commands. The send() method awaits a response, which is resolved by
        # the listener loop receiving incoming messages. If the listener isn't
        # running, send() hangs indefinitely — this was the root cause of the
        # "Active tab is not connected" bug through v1.9.20.
        self._browser._listener_task = asyncio.create_task(self._browser._listen_loop())

        # Enable core domains (now the listener can process responses)
        await self._browser.send("Page.enable")
        await self._browser.send("Runtime.enable")

        self._connected = True
        logger.info("[CDPTab] Connected to tab %s (%s)", self.target_id, self.title or self.url)

    async def disconnect(self) -> None:
        """Disconnect from this tab (does NOT close the browser tab)."""
        if self._browser:
            await self._browser.close()
            self._browser = None
        self._connected = False
        logger.info("[CDPTab] Disconnected from tab %s", self.target_id)

    async def refresh_info(self) -> Dict[str, str]:
        """Refresh title and URL from the live page.

        Returns:
            Dict with 'title' and 'url' keys.
        """
        if not self._connected:
            return {"title": self.title, "url": self.url}

        try:
            self.title = await self.get_title() or self.title
            self.url = await self.get_current_url() or self.url
        except Exception:
            pass
        return {"title": self.title, "url": self.url}

    # -- Delegated CDP operations --------------------------------------------

    async def send(self, method: str, params: Optional[Dict] = None,
                   timeout: Optional[float] = None) -> Dict:
        """Send a raw CDP command via this tab's connection."""
        if not self._connected or not self._browser:
            raise ConnectionError(f"Tab {self.target_id} is not connected")
        return await self._browser.send(method, params, timeout)

    def on(self, event_name: str, callback: Callable[[Dict], Any]) -> None:
        """Register a callback for a CDP event on this tab."""
        if not self._browser:
            raise ConnectionError(f"Tab {self.target_id} is not connected")
        self._browser.on(event_name, callback)

    def off(self, event_name: str, callback: Callable) -> None:
        """Unregister a callback for a CDP event on this tab."""
        if self._browser:
            self._browser.off(event_name, callback)

    async def wait_for_event(self, event_name: str,
                             timeout: Optional[float] = None) -> Dict:
        """Wait for a specific CDP event on this tab."""
        if not self._connected or not self._browser:
            raise ConnectionError(f"Tab {self.target_id} is not connected")
        return await self._browser.wait_for_event(event_name, timeout)

    async def navigate(self, url: str, wait: bool = True,
                       timeout: Optional[float] = None) -> Dict:
        """Navigate this tab to a URL."""
        if not self._connected or not self._browser:
            raise ConnectionError(f"Tab {self.target_id} is not connected")
        result = await self._browser.navigate(url, wait, timeout)
        self.url = url
        return result

    async def screenshot(self, path: Optional[str] = None,
                         timeout: Optional[float] = None) -> Optional[bytes]:
        """Capture a screenshot of this tab."""
        if not self._connected or not self._browser:
            raise ConnectionError(f"Tab {self.target_id} is not connected")
        return await self._browser.screenshot(path, timeout)

    async def dump_dom(self, timeout: Optional[float] = None) -> Optional[str]:
        """Dump the outerHTML of this tab's page."""
        if not self._connected or not self._browser:
            raise ConnectionError(f"Tab {self.target_id} is not connected")
        return await self._browser.dump_dom(timeout)

    async def eval_js(self, expression: str,
                      timeout: Optional[float] = None) -> Any:
        """Evaluate JavaScript in this tab's page context."""
        if not self._connected or not self._browser:
            raise ConnectionError(f"Tab {self.target_id} is not connected")
        return await self._browser.eval_js(expression, timeout)

    async def click(self, selector: str, timeout: Optional[float] = None) -> bool:
        """Click an element in this tab."""
        if not self._connected or not self._browser:
            raise ConnectionError(f"Tab {self.target_id} is not connected")
        return await self._browser.click(selector, timeout)

    async def click_at(self, x: float, y: float,
                       timeout: Optional[float] = None) -> bool:
        """Click at coordinates in this tab.

        Uses CDP Input.dispatchMouseEvent — can reach iframe content
        (e.g., reCAPTCHA) that CSS selectors cannot.
        """
        if not self._connected or not self._browser:
            raise ConnectionError(f"Tab {self.target_id} is not connected")
        return await self._browser.click_at(x, y, timeout)

    async def type_text(self, selector: str, text: str,
                        timeout: Optional[float] = None) -> bool:
        """Type text into an element in this tab."""
        if not self._connected or not self._browser:
            raise ConnectionError(f"Tab {self.target_id} is not connected")
        return await self._browser.type_text(selector, text, timeout)

    async def wait_for_selector(self, selector: str, poll_interval: float = 0.5,
                                timeout: Optional[float] = None) -> bool:
        """Wait for a CSS selector to appear in this tab."""
        if not self._connected or not self._browser:
            raise ConnectionError(f"Tab {self.target_id} is not connected")
        return await self._browser.wait_for_selector(selector, poll_interval, timeout)

    async def get_current_url(self, timeout: Optional[float] = None) -> Optional[str]:
        """Get the current URL of this tab."""
        if not self._connected or not self._browser:
            return self.url
        return await self._browser.get_current_url(timeout)

    async def get_title(self, timeout: Optional[float] = None) -> Optional[str]:
        """Get the title of this tab's page."""
        if not self._connected or not self._browser:
            return self.title
        return await self._browser.get_title(timeout)

    async def get_cookies(self, timeout: Optional[float] = None) -> List[Dict]:
        """Get cookies for this tab's page."""
        if not self._connected or not self._browser:
            raise ConnectionError(f"Tab {self.target_id} is not connected")
        return await self._browser.get_cookies(timeout)

    # -- Representation ------------------------------------------------------

    def __repr__(self) -> str:
        status = "connected" if self.connected else "disconnected"
        return (
            f"CDPTab(id={self.target_id!r}, title={self.title!r}, "
            f"url={self.url!r}, status={status})"
        )

    def to_dict(self) -> Dict[str, Any]:
        """Serialize tab info to a dict (for API responses)."""
        return {
            "target_id": self.target_id,
            "ws_url": self.ws_url,
            "title": self.title,
            "url": self.url,
            "connected": self.connected,
        }


class CDPTabManager:
    """Multi-tab browser orchestrator.

    Manages multiple CDPTab instances, tracks tab lifecycle events,
    and provides a unified interface for tab operations.

    Usage:
        async with CDPTabManager(port=9222) as mgr:
            # Create a new tab
            tab = await mgr.new_tab("https://example.com")

            # List all tabs
            for t in mgr.list_tabs():
                print(t)

            # Switch active tab
            mgr.activate(tab.target_id)

            # Get a specific tab
            tab = mgr.get_tab(target_id)

            # Close a tab
            await mgr.close_tab(target_id)

    Events:
        Register callbacks for tab lifecycle events:
            mgr.on_tab_created(callback)
            mgr.on_tab_destroyed(callback)
            mgr.on_tab_navigated(callback)

        Callback receives a dict with:
            - 'tab': CDPTab instance
            - 'event': event type string
            - 'info': additional event info dict
    """

    def __init__(
        self,
        port: int = DEFAULT_PORT,
        headless: bool = True,
        auto_launch: bool = True,
        timeout: float = DEFAULT_TIMEOUT,
        auto_discover_existing: bool = True,
    ):
        self.port = port
        self.headless = headless
        self.auto_launch = auto_launch
        self.timeout = timeout
        self.auto_discover_existing = auto_discover_existing

        self._tabs: Dict[str, CDPTab] = {}  # target_id → CDPTab
        self._active_tab_id: Optional[str] = None
        self._browser_proc: Optional[subprocess.Popen] = None
        self._closing = False

        # Browser-level WebSocket for Target.* events
        self._browser_ws: Optional[aiohttp.ClientWebSocketResponse] = None
        self._browser_session: Optional[aiohttp.ClientSession] = None
        self._browser_listener_task: Optional[asyncio.Task] = None
        self._browser_req_id = itertools.count(1)
        self._browser_pending: Dict[int, asyncio.Future] = {}

        # Lifecycle event callbacks
        self._tab_created_callbacks: List[Callable] = []
        self._tab_destroyed_callbacks: List[Callable] = []
        self._tab_navigated_callbacks: List[Callable] = []

        # Track fire-and-forget callback tasks for cleanup
        self._callback_tasks: List[asyncio.Task] = []

        # WS diagnostics — populated during connect() for API response
        self.ws_diagnostics: Dict[str, Any] = {}

    # -- Context manager -----------------------------------------------------

    async def __aenter__(self):
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()

    def __del__(self):
        if self._browser_proc or self._browser_session:
            logger.warning(
                "CDPTabManager was not properly closed. "
                "Call 'await mgr.close()' or use 'async with'."
            )

    # -- Properties ----------------------------------------------------------

    @property
    def active_tab(self) -> Optional[CDPTab]:
        """Get the currently active tab."""
        if self._active_tab_id and self._active_tab_id in self._tabs:
            return self._tabs[self._active_tab_id]
        return None

    @property
    def tab_count(self) -> int:
        """Number of tracked tabs."""
        return len(self._tabs)

    @property
    def active_tab_id(self) -> Optional[str]:
        """Get the target ID of the currently active tab."""
        return self._active_tab_id

    # -- Connection management -----------------------------------------------

    async def connect(self) -> None:
        """Connect to the browser and discover existing tabs."""
        if not HAS_AIOHTTP:
            raise RuntimeError("aiohttp is required for CDPTabManager. Install with: pip install aiohttp")

        t0 = time.monotonic()
        logger.info("[CDPManager] connect() START port=%d", self.port)

        # Auto-launch browser if needed
        loop = asyncio.get_running_loop()

        # Kill any stale Chromium processes on the target port first.
        # This prevents leftover processes from previous failed attempts
        # or test-launch from interfering with the connection.
        try:
            killed = await loop.run_in_executor(None, _kill_port_processes, self.port)
            if killed:
                logger.info("[CDPManager] Killed stale processes on port %d: %s", self.port, killed)
                # Wait a moment for the port to be released
                await asyncio.sleep(0.5)
        except Exception as e:
            logger.warning("[CDPManager] Failed to kill stale processes: %s", e)

        # Check for existing browser — use short timeout, don't hang
        try:
            existing_tabs = await loop.run_in_executor(None, list_tabs, self.port)
        except Exception:
            existing_tabs = []
        logger.info("[CDPManager] list_tabs=%d tabs (%.1fs)", len(existing_tabs), time.monotonic()-t0)

        # Collect WS diagnostics for API response
        self.ws_diagnostics["list_tabs_count"] = len(existing_tabs)
        if existing_tabs:
            self.ws_diagnostics["tab_ws_urls"] = [
                t.get("webSocketDebuggerUrl", "NONE")[:60] for t in existing_tabs
            ]
            # v1.9.18: Log raw tab info for debugging WS URL issues
            for i, t in enumerate(existing_tabs[:5]):  # First 5 tabs max
                logger.info("[CDPManager]   raw_tab[%d]: type=%s id=%s wsUrl=%s url=%s",
                            i, t.get("type", "?"), t.get("id", "?")[:20],
                            t.get("webSocketDebuggerUrl", "NONE")[:60],
                            t.get("url", "?")[:50])

        if not existing_tabs and self.auto_launch:
            # Run launch_browser in executor to avoid blocking the event loop
            logger.info("[CDPManager] Launching browser via executor...")
            self._browser_proc = await loop.run_in_executor(
                None, launch_browser, self.port, self.headless)
            elapsed_launch = time.monotonic() - t0
            logger.info("[CDPManager] launch_browser returned (%.1fs)", elapsed_launch)

            # launch_browser() now returns IMMEDIATELY (no sleep checks).
            # We need to wait for Chromium to actually start and bind the port.

            # First, give Chromium a moment to start, then check if it crashed
            await asyncio.sleep(1)

            if self._browser_proc and self._browser_proc.poll() is not None:
                # Process already exited — gather diagnostics
                launch_diag = getattr(self._browser_proc, '_cdp_launch_diag', {})
                stderr_info = ""
                stderr_log = launch_diag.get("stderr_log", "")
                if stderr_log and os.path.exists(stderr_log):
                    try:
                        with open(stderr_log, "r") as f:
                            stderr_info = f.read().strip()[:2000]
                    except Exception:
                        pass
                rc = self._browser_proc.returncode
                method = launch_diag.get("method", "unknown")
                logger.error("[CDPManager] Browser EXITED (rc=%s, method=%s) stderr=%s",
                             rc, method, stderr_info[:300])
                raise ConnectionError(
                    f"Browser process exited (rc={rc}, method={method}). "
                    f"stderr: {stderr_info[:500] or '(empty)'}. "
                    f"Launch diag: {launch_diag}"
                )

            # Wait for Chromium to initialize and open the debug port
            # Poll every 0.5 seconds, up to 20 seconds (generous for slow systems)
            for attempt in range(40):
                try:
                    existing_tabs = await loop.run_in_executor(None, list_tabs, self.port)
                except Exception:
                    existing_tabs = []
                if existing_tabs:
                    logger.info("[CDPManager] Port ready! %d tab(s) after %.1fs",
                                len(existing_tabs), (attempt+1)*0.5)
                    break
                # Check if browser process died during startup
                if self._browser_proc and self._browser_proc.poll() is not None:
                    launch_diag = getattr(self._browser_proc, '_cdp_launch_diag', {})
                    stderr_info = ""
                    stderr_log = launch_diag.get("stderr_log", "")
                    if stderr_log and os.path.exists(stderr_log):
                        try:
                            with open(stderr_log, "r") as f:
                                stderr_info = f.read().strip()[:2000]
                        except Exception:
                            pass
                    logger.error("[CDPManager] Browser CRASHED during startup (rc=%s) stderr=%s",
                                 self._browser_proc.returncode, stderr_info[:300])
                    raise ConnectionError(
                        f"Browser crashed during startup (rc={self._browser_proc.returncode}). "
                        f"stderr: {stderr_info[:500] or '(empty)'}. "
                        f"Launch diag: {launch_diag}"
                    )
                await asyncio.sleep(0.5)
            else:
                # Port never became ready — gather diagnostics before raising
                launch_diag = getattr(self._browser_proc, '_cdp_launch_diag', {}) if self._browser_proc else {}
                stderr_info = ""
                stderr_log = launch_diag.get("stderr_log", "")
                if stderr_log and os.path.exists(stderr_log):
                    try:
                        with open(stderr_log, "r") as f:
                            stderr_info = f.read().strip()[:2000]
                    except Exception:
                        pass
                is_alive = self._browser_proc and self._browser_proc.poll() is None
                logger.error("[CDPManager] Port NOT ready after 20s. alive=%s stderr=%s diag=%s",
                             is_alive, stderr_info[:200], launch_diag)
                if is_alive:
                    raise ConnectionError(
                        f"Browser is running (pid={self._browser_proc.pid}) but debug port "
                        f"{self.port} is not responding after 20 seconds. "
                        f"stderr: {stderr_info[:300] or '(empty)'}. "
                        f"Launch diag: {launch_diag}"
                    )
                else:
                    raise ConnectionError(
                        f"Browser exited and debug port {self.port} never became ready. "
                        f"stderr: {stderr_info[:300] or '(empty)'}. "
                        f"Launch diag: {launch_diag}"
                    )

        # Try to connect browser-level WebSocket for Target events
        # This is NON-FATAL — if it fails, we still connect to tabs individually.
        logger.info("[CDPManager] Connecting browser-level WebSocket (%.1fs)...", time.monotonic()-t0)
        await self._connect_browser_ws()
        ws_connected = self._browser_ws is not None and not self._browser_ws.closed
        self.ws_diagnostics["browser_ws_connected"] = ws_connected
        if ws_connected:
            logger.info("[CDPManager] Browser-level WS connected (%.1fs)", time.monotonic()-t0)
        else:
            logger.warning("[CDPManager] Browser-level WS NOT connected (tab events disabled) (%.1fs)", time.monotonic()-t0)

        # Discover and optionally connect existing tabs
        logger.info("[CDPManager] Discovering tabs from %d entries...", len(existing_tabs))
        if self.auto_discover_existing:
            for tab_info in existing_tabs:
                tab_type = tab_info.get("type", "?")
                target_id = tab_info.get("id", "")
                ws_url = tab_info.get("webSocketDebuggerUrl", "")
                tab_url = tab_info.get("url", "")
                logger.info("[CDPManager]   tab: type=%s id=%s ws=%s url=%s",
                            tab_type, target_id[:20] if target_id else "?",
                            ws_url[:50] if ws_url else "NONE", tab_url[:50])
                if tab_type != "page":
                    continue
                if not target_id:
                    logger.warning("[CDPManager]   Skipping tab: missing target id")
                    continue

                # v1.9.18: Construct WS URL from target_id if webSocketDebuggerUrl
                # is missing. Some Chromium builds (e.g. CachyOS) don't populate
                # this field in /json/list, especially in headless mode with
                # --remote-debugging-address=127.0.0.1.
                if not ws_url:
                    ws_url = f"ws://127.0.0.1:{self.port}/devtools/page/{target_id}"
                    logger.info("[CDPManager]   Constructed tab WS URL: %s", ws_url)
                    self.ws_diagnostics.setdefault("constructed_ws_urls", []).append(ws_url)

                if target_id in self._tabs:
                    continue  # Already tracked

                tab = CDPTab(
                    target_id=target_id,
                    ws_url=ws_url,
                    port=self.port,
                    timeout=self.timeout,
                    title=tab_info.get("title", ""),
                    url=tab_url,
                )
                self._tabs[target_id] = tab

                # Set first page tab as active
                if self._active_tab_id is None:
                    self._active_tab_id = target_id

        # Auto-connect to the active tab so operations work immediately
        # CRITICAL FIX (v1.9.15): Wrap in asyncio.wait_for to prevent hanging.
        # The CDPTab.connect() now also has its own timeout, but we add an
        # outer timeout as an additional safety net.
        tab_connected = False
        if self._active_tab_id and self._active_tab_id in self._tabs:
            active_tab = self._tabs[self._active_tab_id]
            logger.info("[CDPManager] Auto-connecting to active tab %s (%.1fs)... ws_url=%s",
                        self._active_tab_id, time.monotonic()-t0, active_tab.ws_url[:60])
            try:
                await asyncio.wait_for(
                    active_tab.connect(),
                    timeout=25  # v1.9.18: increased to cover 4 strategies (7+5+8+5s)
                )
                tab_connected = active_tab.connected
                logger.info("[CDPTabManager] Auto-connected to active tab %s (%.1fs)",
                            self._active_tab_id, time.monotonic()-t0)
            except asyncio.TimeoutError:
                logger.error("[CDPTabManager] Auto-connect to active tab %s TIMED OUT (25s)!", self._active_tab_id)
                logger.error("[CDPTabManager] WS URL was: %s", active_tab.ws_url)
                self.ws_diagnostics["tab_ws_error"] = f"TIMEOUT (25s). WS URL: {active_tab.ws_url}"
                # Don't raise — we'll try to continue without an active tab connection
            except Exception as e:
                logger.warning("[CDPTabManager] Failed to auto-connect active tab: %s\n%s", e, traceback.format_exc())
                self.ws_diagnostics["tab_ws_error"] = f"{type(e).__name__}: {e}"

            # v1.9.20: If CDPTab.connect() failed all strategies, try a DIRECT
            # websockets connection and wire it into the tab's CDPBrowser.
            # The previous "probe only" approach just tested connectivity but
            # left the tab disconnected. Now we USE the working connection.
            if not tab_connected and active_tab and active_tab.ws_url:
                logger.info("[CDPManager] CDPTab.connect() failed. Trying direct websockets fallback to %s",
                            active_tab.ws_url[:60])
                self.ws_diagnostics["direct_fallback_url"] = active_tab.ws_url

                # Strategy A: websockets library direct connection
                if HAS_WEBSOCKETS:
                    try:
                        direct_ws = await asyncio.wait_for(
                            _websockets_mod.connect(active_tab.ws_url, open_timeout=5, close_timeout=3),
                            timeout=7
                        )
                        logger.info("[CDPManager] Direct websockets fallback SUCCEEDED!")
                        self.ws_diagnostics["direct_fallback_ok"] = True
                        self.ws_diagnostics["direct_fallback_lib"] = "websockets"

                        # Wire the working connection into the tab's CDPBrowser
                        browser_inst = CDPBrowser(
                            port=self.port, auto_launch=False, timeout=self.timeout
                        )
                        browser_inst._ws = WebsocketsCDPAdapter(direct_ws)
                        browser_inst._session = None
                        browser_inst._closing = True  # Prevent auto-reconnect

                        # Start listener FIRST — it must be running to process
                        # responses from Page.enable/Runtime.enable
                        browser_inst._listener_task = asyncio.create_task(browser_inst._listen_loop())

                        # Enable core CDP domains (listener will process responses)
                        try:
                            await browser_inst.send("Page.enable")
                            await browser_inst.send("Runtime.enable")
                        except Exception as e:
                            logger.warning("[CDPManager] CDP domain enable failed (non-fatal): %s", e)

                        # Set the tab as connected
                        active_tab._browser = browser_inst
                        active_tab._connected = True
                        tab_connected = True

                        logger.info("[CDPManager] Tab %s CONNECTED via direct websockets fallback!",
                                    active_tab.target_id)
                    except asyncio.TimeoutError:
                        logger.warning("[CDPManager] Direct websockets fallback TIMED OUT (7s)")
                        self.ws_diagnostics["direct_fallback_ok"] = False
                        self.ws_diagnostics["direct_fallback_error"] = "TIMEOUT (7s)"
                    except Exception as e:
                        logger.warning("[CDPManager] Direct websockets fallback FAILED: %s\n%s",
                                       e, traceback.format_exc())
                        self.ws_diagnostics["direct_fallback_ok"] = False
                        self.ws_diagnostics["direct_fallback_error"] = f"{type(e).__name__}: {e}"

                # Strategy B: aiohttp direct connection (if websockets failed or unavailable)
                if not tab_connected:
                    logger.info("[CDPManager] Trying direct aiohttp fallback to %s",
                                active_tab.ws_url[:60])
                    aiohttp_session = None
                    try:
                        ws_timeout = aiohttp.ClientTimeout(total=5, connect=3, sock_connect=3)
                        connector = aiohttp.TCPConnector(force_close=True, enable_cleanup_closed=True)
                        aiohttp_session = aiohttp.ClientSession(timeout=ws_timeout, connector=connector)
                        direct_ws = await asyncio.wait_for(
                            aiohttp_session.ws_connect(active_tab.ws_url, heartbeat=None, proxy=None),
                            timeout=7
                        )
                        logger.info("[CDPManager] Direct aiohttp fallback SUCCEEDED!")
                        self.ws_diagnostics["direct_aiohttp_fallback_ok"] = True
                        self.ws_diagnostics["direct_fallback_lib"] = "aiohttp"

                        # Wire the working connection into the tab's CDPBrowser
                        browser_inst = CDPBrowser(
                            port=self.port, auto_launch=False, timeout=self.timeout
                        )
                        browser_inst._ws = direct_ws
                        browser_inst._session = aiohttp_session
                        browser_inst._closing = True  # Prevent auto-reconnect

                        # Start listener FIRST — it must be running to process
                        # responses from Page.enable/Runtime.enable
                        browser_inst._listener_task = asyncio.create_task(browser_inst._listen_loop())

                        # Enable core CDP domains (listener will process responses)
                        try:
                            await browser_inst.send("Page.enable")
                            await browser_inst.send("Runtime.enable")
                        except Exception as e:
                            logger.warning("[CDPManager] CDP domain enable failed (non-fatal): %s", e)

                        # Set the tab as connected
                        active_tab._browser = browser_inst
                        active_tab._connected = True
                        tab_connected = True

                        logger.info("[CDPManager] Tab %s CONNECTED via direct aiohttp fallback!",
                                    active_tab.target_id)
                    except asyncio.TimeoutError:
                        logger.warning("[CDPManager] Direct aiohttp fallback TIMED OUT (7s)")
                        self.ws_diagnostics["direct_aiohttp_fallback_ok"] = False
                        self.ws_diagnostics["direct_aiohttp_fallback_error"] = "TIMEOUT (7s)"
                        if aiohttp_session and not aiohttp_session.closed:
                            await aiohttp_session.close()
                    except Exception as e:
                        logger.warning("[CDPManager] Direct aiohttp fallback FAILED: %s", e)
                        self.ws_diagnostics["direct_aiohttp_fallback_ok"] = False
                        self.ws_diagnostics["direct_aiohttp_fallback_error"] = f"{type(e).__name__}: {e}"
                        if aiohttp_session and not aiohttp_session.closed:
                            try:
                                await aiohttp_session.close()
                            except Exception:
                                pass
        else:
            self.ws_diagnostics["tab_ws_connected"] = self._tabs[self._active_tab_id].connected if self._active_tab_id else False

        logger.info(
            "[CDPTabManager] Connected. Tracking %d tab(s), active: %s (%.1fs)",
            len(self._tabs),
            self._active_tab_id or "none",
            time.monotonic()-t0,
        )

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
            # Browser WS connected but Target domain failed — still usable for raw events

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

    # -- Tab operations ------------------------------------------------------

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

    # -- Lifecycle event callbacks -------------------------------------------

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

    @staticmethod
    def _log_callback_error(task: asyncio.Task) -> None:
        """Log exceptions from fire-and-forget callback tasks."""
        if not task.cancelled():
            try:
                task.exception()
            except Exception as e:
                logger.error("[CDPTabManager] Async callback task error: %s", e)

    # -- Cleanup -------------------------------------------------------------

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

    # -- Representation ------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Synchronous fallback (raw socket, no aiohttp needed)
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# CLI entry point (backward compatible)
# ---------------------------------------------------------------------------
def main():
    """Synchronous CLI — works without aiohttp."""
    if len(sys.argv) < 2:
        print("Usage: python3 cdp_browser.py <command> [args...]")
        print("Commands:")
        print("  navigate <url>      Open browser and navigate to URL")
        print("  shot [png_path]     Capture screenshot of active page")
        print("  dump                Dump active page outerHTML")
        print("  eval <js>           Evaluate JavaScript in page context")
        print("  tabs                List open browser tabs")
        print("  new <url>           Open a new tab with URL")
        print("  multitab            Interactive multi-tab management demo (async)")
        print("  close <tab_id>      Close a tab by ID")
        print("  activate <tab_id>   Activate a tab by ID")
        sys.exit(1)

    cmd = sys.argv[1].lower()
    logging.basicConfig(level=logging.INFO, format="[CDP] %(message)s")

    if cmd == "tabs":
        tabs = list_tabs()
        if tabs:
            for i, t in enumerate(tabs):
                print(f"  [{i}] {t.get('title', '(no title)')} — {t.get('url', '')}")
        else:
            print("No tabs found. Is the browser running with --remote-debugging-port?")
        return

    if cmd == "new":
        url = sys.argv[2] if len(sys.argv) > 2 else "about:blank"
        ws = get_new_tab_url()
        if ws:
            print(f"[OK] New tab opened. WebSocket: {ws}")
        else:
            print("[ERROR] Failed to open new tab.")
        return

    if cmd == "close":
        if len(sys.argv) < 3:
            print("Provide tab ID to close")
            sys.exit(1)
        tab_id = sys.argv[2]
        if close_tab(tab_id):
            print(f"[OK] Tab {tab_id} closed.")
        else:
            print(f"[ERROR] Failed to close tab {tab_id}.")
        return

    if cmd == "activate":
        if len(sys.argv) < 3:
            print("Provide tab ID to activate")
            sys.exit(1)
        # Activation requires async — use HTTP /json/activate endpoint
        tab_id = sys.argv[2]
        try:
            url = f"http://127.0.0.1:{DEFAULT_PORT}/json/activate/{tab_id}"
            with urllib.request.urlopen(url, timeout=5) as r:
                result = r.read().decode().strip()
                if result == "Target activated":
                    print(f"[OK] Tab {tab_id} activated.")
                else:
                    print(f"[?] Unexpected response: {result}")
        except Exception as e:
            print(f"[ERROR] Failed to activate tab: {e}")
        return

    if cmd == "multitab":
        if not HAS_AIOHTTP:
            print("[ERROR] multitab command requires aiohttp. Install with: pip install aiohttp")
            sys.exit(1)
        asyncio.run(_multitab_demo())
        return

    # All other commands need an active CDP connection
    with SyncCDPBrowser() as browser:
        if cmd == "navigate":
            if len(sys.argv) < 3:
                print("Provide a URL")
                sys.exit(1)
            url = sys.argv[2]
            print(f"[CDP] Navigating to {url}...")
            browser.navigate(url)
            print("[OK] Navigation completed.")

        elif cmd == "shot":
            path = sys.argv[2] if len(sys.argv) > 2 else "screenshot_cdp.png"
            print(f"[CDP] Capturing screenshot to {path}...")
            if browser.screenshot(path):
                print(f"[OK] Screenshot written to {path} ({os.path.getsize(path)} bytes)")
            else:
                print("[ERROR] Failed to capture screenshot.")

        elif cmd == "dump":
            print("[CDP] Dumping DOM (outerHTML)...")
            html = browser.dump_dom()
            if html:
                print(html)
            else:
                print("[ERROR] Failed to dump DOM.")

        elif cmd == "eval":
            if len(sys.argv) < 3:
                print("Provide JS expression")
                sys.exit(1)
            expr = " ".join(sys.argv[2:])
            print(f"[CDP] Evaluating: {expr}")
            result = browser.eval_js(expr)
            if result:
                print(result)
            else:
                print("[ERROR] Failed to evaluate.")

        else:
            print(f"Unknown command: {cmd}")
            sys.exit(1)


async def _multitab_demo():
    """Interactive multi-tab management demo using CDPTabManager."""
    print("=" * 60)
    print("  CDP Multi-Tab Manager Demo")
    print("=" * 60)

    async with CDPTabManager(headless=True) as mgr:
        print(f"\n[Manager] Connected. Tabs tracked: {mgr.tab_count}")

        # Create 3 tabs with different URLs
        urls = [
            "https://example.com",
            "https://httpbin.org/html",
            "https://www.wikipedia.org",
        ]

        tabs = []
        for url in urls:
            try:
                tab = await mgr.new_tab(url)
                tabs.append(tab)
                print(f"  [+] Tab created: {tab.target_id[:12]}... → {url}")
            except Exception as e:
                print(f"  [!] Failed to create tab for {url}: {e}")

        # List all tabs
        print(f"\n[Manager] {mgr.tab_count} tabs:")
        for i, tab in enumerate(mgr.list_tabs()):
            marker = " *" if tab.target_id == mgr.active_tab_id else "  "
            conn = "●" if tab.connected else "○"
            print(f"  {marker}[{i}] {conn} {tab.target_id[:12]}... | {tab.title[:40] or '(no title)'} | {tab.url[:50]}")

        # Take screenshot of active tab
        active = mgr.active_tab
        if active:
            print(f"\n[Active Tab] Taking screenshot...")
            try:
                await active.screenshot("multitab_active.png")
                print(f"  [OK] Screenshot saved: multitab_active.png")
            except Exception as e:
                print(f"  [!] Screenshot failed: {e}")

            # Get title
            try:
                title = await active.get_title()
                print(f"  [Title] {title}")
            except Exception:
                pass

        # Switch active tab
        if len(tabs) > 1:
            second_tab = tabs[1]
            mgr.activate(second_tab.target_id)
            print(f"\n[Manager] Switched active tab to: {second_tab.target_id[:12]}...")

            # Navigate the newly active tab
            try:
                await second_tab.navigate("https://example.org")
                print(f"  [OK] Navigated to example.org")
                title = await second_tab.get_title()
                print(f"  [Title] {title}")
            except Exception as e:
                print(f"  [!] Navigation failed: {e}")

        # Close the first tab
        if tabs:
            first_id = tabs[0].target_id
            success = await mgr.close_tab(first_id)
            print(f"\n[Manager] Closed tab {first_id[:12]}...: {'OK' if success else 'FAILED'}")
            print(f"  Remaining tabs: {mgr.tab_count}")

        # Final sync
        final_tabs = await mgr.sync_tabs()
        print(f"\n[Manager] Final tab count: {len(final_tabs)}")

    print("\n[Manager] Demo complete. Browser closed.")


if __name__ == "__main__":
    main()


# ---------------------------------------------------------------------------
# Network monitoring and interception
# ---------------------------------------------------------------------------









# ---------------------------------------------------------------------------
# Cookie and session management
# ---------------------------------------------------------------------------

