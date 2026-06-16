"""Extracted CDP browser component."""
from __future__ import annotations

from arena.browser.cdp_client.common import *  # noqa: F401,F403
from arena.browser.cdp_client.tabs_http import get_new_tab_url, close_tab, list_tabs

from arena.browser.cdp_client.browser_input import CDPBrowserInputMixin

class CDPBrowserPageMixin(CDPBrowserInputMixin):
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
