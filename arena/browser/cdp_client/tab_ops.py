"""Extracted CDP browser component."""
from __future__ import annotations

from cdp_browser_modules.common import *  # noqa: F401,F403
from cdp_browser_modules.process import launch_browser
from cdp_browser_modules.tabs_http import get_websocket_url, list_tabs, get_new_tab_url, close_tab
from cdp_browser_modules.websocket_adapter import WebsocketsCDPAdapter

class CDPTabOpsMixin:
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
