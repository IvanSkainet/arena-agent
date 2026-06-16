"""Extracted CDP browser component."""
from __future__ import annotations

from cdp_browser_modules.common import *  # noqa: F401,F403
from cdp_browser_modules.tabs_http import get_new_tab_url, close_tab, list_tabs

class CDPBrowserInputMixin:
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
