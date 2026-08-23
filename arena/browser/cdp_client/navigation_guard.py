"""Re-apply the navigation policy to every main-frame document request (#122).

``check_navigation()`` validates the URL an agent supplies. Chromium then
follows redirects inside its own network stack, and a 30x does not re-enter
the policy -- so a public URL answering ``302 Location: http://127.0.0.1:.../``
reached loopback with no second check.

Demonstrated end to end on live Chromium before this was written: a real
``https://`` start URL on a public host, accepted by the policy, redirected to
a loopback HTTP server, and the secret served there was read back out of the
DOM. This is the same TOCTOU family as DNS rebinding, but unlike rebinding the
redirect half is fixable -- the browser tells us about it.

Scope, deliberately narrow
--------------------------
Only ``resourceType == "Document"`` on the **top** frame is judged. Subresources
(images, XHR, iframes) are a different policy question with a different blast
radius -- a page legitimately loading a CDN image is not a navigation, and
blocking those here would break ordinary pages while adding no protection the
navigation policy promised. What this closes is exactly the documented gap:
*navigation* reaching a private target.

The environment opt-in (``ARENA_BROWSER_ALLOW_LOCAL_NAV=1``) still applies,
because it is evaluated inside ``check_navigation`` -- an operator who opted
into local navigation keeps it across redirects too.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from arena.browser.cdp_client.common import logger
from arena.browser.cdp_client.fetch_arbiter import CLAIMED, NOT_CLAIMED, get_arbiter
from arena.browser.navigation_policy import NavigationRejected, check_navigation

#: Arbiter subscriber name.
GUARD_NAME = "navigation_guard"

#: Consulted before user interception rules: a user rule must not be able to
#: rewrite or mock a request past the SSRF policy.
GUARD_PRIORITY = 0

#: Only document loads are judged; see the module docstring.
DOCUMENT = "Document"


class NavigationGuard:
    """Fails main-frame navigations whose target the policy refuses."""

    def __init__(self, browser: Any, env: Optional[Dict[str, str]] = None) -> None:
        self._browser = browser
        self._env = env
        self._main_frame_id: Optional[str] = None
        self.rejections: list[tuple[str, str]] = []

    async def main_frame_id(self) -> Optional[str]:
        """Top-level frame id, from ``Page.getFrameTree``, cached.

        Verified against live Chromium: the ``frameId`` on a main-frame
        ``Document`` request equals the root of the frame tree.
        """
        if self._main_frame_id is None:
            try:
                tree = await self._browser.send("Page.getFrameTree")
                self._main_frame_id = (
                    tree.get("result", {}).get("frameTree", {}).get("frame", {}).get("id")
                )
            except Exception as exc:  # pragma: no cover - transport dependent
                logger.debug("[NavigationGuard] getFrameTree failed: %s", exc)
                return None
        return self._main_frame_id

    async def _handle(self, params: Dict) -> str:
        if params.get("resourceType") != DOCUMENT:
            return NOT_CLAIMED

        # Subframes carry their own frameId; only the top frame is a
        # navigation in the sense the policy is about. If the top frame id
        # cannot be determined, judge the request anyway -- failing open here
        # would reopen the very hole this module closes.
        frame_id = params.get("frameId")
        top = await self.main_frame_id()
        if top is not None and frame_id is not None and frame_id != top:
            # The cached id survives reconnects and target switches, and a
            # stale one makes a genuine top-level navigation look like a
            # subframe -- skipped, unchecked, fail-open. Only a re-read of the
            # frame tree may excuse a request from judgement.
            self._main_frame_id = None
            top = await self.main_frame_id()
            if top is not None and frame_id != top:
                return NOT_CLAIMED

        url = params.get("request", {}).get("url", "")
        try:
            check_navigation(url, env=self._env)
        except NavigationRejected as exc:
            # Same error strings as the static policy -- one policy, one
            # vocabulary, as the issue requires.
            logger.warning(
                "[NavigationGuard] refused redirect target %.120s: %s", url, exc
            )
            self.rejections.append((url, str(exc)))
            await self._fail(params.get("requestId", ""))
            return CLAIMED
        return NOT_CLAIMED

    async def _fail(self, request_id: str) -> None:
        try:
            await self._browser.send(
                "Fetch.failRequest",
                {"requestId": request_id, "errorReason": "BlockedByClient"},
            )
        except Exception as exc:  # pragma: no cover - transport dependent
            logger.debug("[NavigationGuard] failRequest failed: %s", exc)


async def arm_navigation_guard(
    browser: Any, env: Optional[Dict[str, str]] = None
) -> NavigationGuard:
    """Install the guard on ``browser`` (idempotent) and return it."""
    arbiter = get_arbiter(browser)
    existing = getattr(browser, "_navigation_guard", None)
    if existing is not None and arbiter.is_registered(GUARD_NAME):
        return existing

    guard = existing or NavigationGuard(browser, env=env)
    browser._navigation_guard = guard
    await arbiter.register(
        GUARD_NAME,
        guard._handle,
        patterns=[{"urlPattern": "*", "requestStage": "Request"}],
        priority=GUARD_PRIORITY,
    )
    return guard


async def disarm_navigation_guard(browser: Any) -> None:
    """Remove the guard. Interception stays up if another subscriber wants it."""
    await get_arbiter(browser).unregister(GUARD_NAME)


__all__ = [
    "DOCUMENT",
    "GUARD_NAME",
    "GUARD_PRIORITY",
    "NavigationGuard",
    "arm_navigation_guard",
    "disarm_navigation_guard",
]
