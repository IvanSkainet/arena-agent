"""CDP cookie manager components."""
from __future__ import annotations

from arena.browser.cdp_client.common import *  # noqa: F401,F403

class CDPCookieProfileMixin:
    async def export_cookies(self, domain_filter: Optional[str] = None) -> List[Dict]:
        """Export cookies, optionally filtered by domain.

        Args:
            domain_filter: If specified, only export cookies whose domain
                          contains this substring

        Returns:
            List of cookie dicts suitable for import_cookies()
        """
        cookies = await self.get_all_cookies()
        if domain_filter:
            cookies = [c for c in cookies if domain_filter in c.get("domain", "")]
        return cookies

    async def import_cookies(self, cookies: List[Dict]) -> int:
        """Import a list of cookies into the browser.

        Uses concurrent import for speed with semaphore-limited parallelism.

        Args:
            cookies: List of cookie dicts (as returned by export_cookies)

        Returns:
            Number of cookies successfully imported

        Raises:
            RuntimeError: if cookie manager is not started
        """
        self._ensure_active()
        if not cookies:
            return 0

        sem = asyncio.Semaphore(10)  # Max 10 concurrent cookie sets

        async def _import_one(cookie: Dict) -> bool:
            async with sem:
                return await self.set_cookie(
                    name=cookie.get("name", ""),
                    value=cookie.get("value", ""),
                    domain=cookie.get("domain", ""),
                    path=cookie.get("path", "/"),
                    secure=cookie.get("secure", False),
                    http_only=cookie.get("httpOnly", False),
                    same_site=cookie.get("sameSite", ""),
                    expires=cookie.get("expires"),
                    priority=cookie.get("priority", "Medium"),
                )

        results = await asyncio.gather(*[_import_one(c) for c in cookies], return_exceptions=True)
        count = sum(1 for r in results if r is True)
        logger.info("[CDPCookieManager] Imported %d/%d cookies", count, len(cookies))
        return count

    async def save_profile(self, name: str, domain_filter: Optional[str] = None) -> int:
        """Save current cookies as a named profile.

        Args:
            name: Profile name
            domain_filter: If specified, only save cookies matching this domain

        Returns:
            Number of cookies saved in the profile
        """
        cookies = await self.export_cookies(domain_filter)
        self._profiles[name] = cookies
        logger.info("[CDPCookieManager] Profile '%s' saved with %d cookies", name, len(cookies))
        return len(cookies)

    async def restore_profile(self, name: str, clear_first: bool = True) -> int:
        """Restore a saved cookie profile.

        If clear_first is True, imports cookies FIRST, then clears and re-imports
        to ensure atomicity (rollback on failure).

        Args:
            name: Profile name
            clear_first: If True, clear all existing cookies before restoring

        Returns:
            Number of cookies successfully restored

        Raises:
            KeyError: if the profile name doesn't exist
            RuntimeError: if cookie manager is not started
        """
        self._ensure_active()
        if name not in self._profiles:
            raise KeyError(f"Cookie profile '{name}' not found. Available: {list(self._profiles.keys())}")

        cookies = self._profiles[name]

        if clear_first:
            # Save current state for rollback
            current_cookies = await self.export_cookies()
            await self.clear_cookies()
            count = await self.import_cookies(cookies)
            if count == 0 and len(cookies) > 0:
                # Rollback: restore previous cookies
                logger.warning("[CDPCookieManager] Profile restore failed, rolling back")
                await self.import_cookies(current_cookies)
                return 0
        else:
            count = await self.import_cookies(cookies)

        logger.info("[CDPCookieManager] Profile '%s' restored: %d/%d cookies", name, count, len(cookies))
        return count

    def list_profiles(self) -> List[str]:
        """List all saved profile names."""
        return list(self._profiles.keys())

    def delete_profile(self, name: str) -> bool:
        """Delete a saved profile. Returns True if found and deleted."""
        if name in self._profiles:
            del self._profiles[name]
            return True
        return False

    def get_profile_info(self, name: str) -> Optional[Dict]:
        """Get info about a saved profile without restoring it."""
        if name not in self._profiles:
            return None
        cookies = self._profiles[name]
        domains = set(c.get("domain", "") for c in cookies)
        return {
            "name": name,
            "cookie_count": len(cookies),
            "domains": sorted(domains),
        }

    async def check_session(self, domain: str, auth_cookie_names: Optional[List[str]] = None) -> Dict[str, Any]:
        """Check the health of a login session for a domain.

        Examines cookies for the given domain and reports on session health:
          - Whether auth-related cookies exist
          - Whether any cookies are expired or about to expire
          - Session cookie count and domains

        Args:
            domain: Domain to check (e.g., "example.com")
            auth_cookie_names: List of cookie names that indicate authentication.
                             If None, looks for common patterns: session, token, auth, sid.

        Returns:
            Dict with session health information
        """
        cookies = await self.get_cookies_for_url(f"https://{domain}")
        # Also check HTTP scheme for non-secure cookies
        if not cookies:
            cookies_http = await self.get_cookies_for_url(f"http://{domain}")
            cookies = cookies_http or cookies
        now = time.time()

        if auth_cookie_names is None:
            auth_cookie_names = ["session", "token", "auth", "sid", "sessionid",
                                "session_id", "access_token", "refresh_token",
                                "jwt", "csrf"]

        auth_cookies = []
        expiring_soon = []
        expired = []

        for c in cookies:
            name_lower = c.get("name", "").lower()
            # Check if this is an auth cookie
            is_auth = any(pattern in name_lower for pattern in auth_cookie_names)
            if is_auth:
                auth_cookies.append(c)

            # Check expiration
            expires = c.get("expires", -1)
            if expires > 0:
                if expires < now:
                    expired.append(c)
                elif expires < now + 3600:  # Within 1 hour
                    expiring_soon.append(c)

        has_auth = len(auth_cookies) > 0
        all_cookies_count = len(cookies)

        return {
            "domain": domain,
            "healthy": has_auth and len(expired) == 0,
            "has_auth_cookies": has_auth,
            "auth_cookies": [c.get("name") for c in auth_cookies],
            "total_cookies": all_cookies_count,
            "expired_count": len(expired),
            "expiring_soon_count": len(expiring_soon),
            "expired": [c.get("name") for c in expired],
            "expiring_soon": [c.get("name") for c in expiring_soon],
        }
