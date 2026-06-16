"""CDP cookie manager components."""
from __future__ import annotations

from cdp_browser_modules.common import *  # noqa: F401,F403

class CDPCookieCrudMixin:
    def _ensure_active(self) -> None:
        """Raise RuntimeError if cookie manager is not started."""
        if not self._active:
            raise RuntimeError("CDPCookieManager is not started. Call await mgr.start() first.")

    async def get_all_cookies(self) -> List[Dict]:
        """Get ALL cookies from the browser (across all domains).

        Returns:
            List of cookie dicts with name, value, domain, path, etc.

        Raises:
            RuntimeError: if cookie manager is not started
        """
        self._ensure_active()
        res = await self._browser.send("Network.getAllCookies")
        if res and "result" in res:
            return res["result"].get("cookies", [])
        return []

    async def get_cookies_for_url(self, url: str) -> List[Dict]:
        """Get cookies that would be sent with a request to the given URL.

        Args:
            url: The URL to match cookies against

        Returns:
            List of matching cookie dicts

        Raises:
            RuntimeError: if cookie manager is not started
        """
        self._ensure_active()
        res = await self._browser.send("Network.getCookies", {"urls": [url]})
        if res and "result" in res:
            return res["result"].get("cookies", [])
        return []

    async def set_cookie(self, name: str, value: str, domain: str = "",
                         path: str = "/", secure: bool = False,
                         http_only: bool = False, same_site: str = "",
                         expires: Optional[float] = None,
                         priority: str = "Medium",
                         same_party: bool = False,
                         source_scheme: str = "NonSecure") -> bool:
        """Set a cookie with full options.

        Args:
            name: Cookie name (must not be empty)
            value: Cookie value
            domain: Cookie domain (e.g., ".example.com")
            path: Cookie path (default: "/")
            secure: Whether the cookie requires HTTPS
            http_only: Whether the cookie is HTTP-only (no JS access)
            same_site: SameSite policy ("Strict", "Lax", "None", or "")
            expires: Expiration as UTC timestamp (None = session cookie)
            priority: Cookie priority ("Low", "Medium", "High")
            same_party: SameParty attribute
            source_scheme: "Secure" or "NonSecure"

        Returns:
            True if the cookie was set successfully

        Raises:
            ValueError: if name is empty or same_site is invalid
            RuntimeError: if cookie manager is not started
        """
        self._ensure_active()
        if not name:
            raise ValueError("Cookie name must not be empty")
        if same_site and same_site not in ("Strict", "Lax", "None"):
            raise ValueError(f"Invalid sameSite value: {same_site!r}. Must be Strict, Lax, None, or empty.")
        params = {
            "name": name,
            "value": value,
            "path": path,
            "secure": secure,
            "httpOnly": http_only,
            "priority": priority,
            "sameParty": same_party,
            "sourceScheme": source_scheme,
        }
        if domain:
            params["domain"] = domain
        if same_site:
            params["sameSite"] = same_site
        if expires is not None:
            params["expires"] = expires

        res = await self._browser.send("Network.setCookie", params)
        return res and res.get("result", {}).get("success", False)

    async def delete_cookie(self, name: str, domain: str = "",
                            path: str = "/") -> None:
        """Delete a cookie by name, optionally filtered by domain and path.

        Args:
            name: Cookie name to delete
            domain: If specified, only delete cookies matching this domain
            path: If specified, only delete cookies matching this path

        Raises:
            RuntimeError: if cookie manager is not started
        """
        self._ensure_active()
        params = {"name": name}
        if domain:
            params["domain"] = domain
        if path:
            params["path"] = path
        await self._browser.send("Network.deleteCookies", params)

    async def clear_cookies(self) -> None:
        """Clear ALL cookies from the browser.

        Raises:
            RuntimeError: if cookie manager is not started
        """
        self._ensure_active()
        await self._browser.send("Network.clearBrowserCookies")
