"""Single owner for the CDP ``Fetch`` domain.

Why this exists
---------------
``Fetch`` is a global, single-slot domain per CDP session, and two subsystems
now want it: the user-facing interception rules (``intercept_runtime.py``) and
the navigation guard that re-applies the SSRF policy to redirects (#122).
Measured against live Chromium rather than assumed:

* a second ``Fetch.enable`` **replaces** the first one's patterns -- it is not
  additive, so the last caller silently wins and the other subsystem stops
  seeing requests;
* ``Fetch.disable`` is **global** -- whichever subsystem stops first disarms
  the other, which for the guard means silently dropping the SSRF check;
* a redirect target arrives as its **own** ``Fetch.requestPaused`` event with
  ``resourceType == "Document"``, which is what makes per-navigation
  enforcement possible at all.

Left uncoordinated, "interception is on" and "the guard is armed" are the same
bit of state fought over by two owners. So neither subsystem talks to ``Fetch``
directly any more: both register here, this module owns enable/disable, and it
guarantees exactly one disposition per paused request.

Ordering
--------
Subscribers are consulted by ascending ``priority``. The guard registers at
priority 0 so a rejected navigation is failed before any user rule can rewrite,
mock, or allow it -- a user rule must not be able to launder a request past the
SSRF policy. The first subscriber to claim a request owns its disposition.

Fail-closed
-----------
If a subscriber raises, the request is failed rather than continued: a guard
that crashed is not evidence that a navigation is safe. If *no* subscriber
claims a request, it is continued -- that is the ordinary case for traffic
nobody has an opinion about, and a missed continue hangs the page.
"""

from __future__ import annotations

import asyncio
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple

from arena.browser.cdp_client.common import logger

#: Returned by a subscriber that has taken responsibility for a request.
CLAIMED = "claimed"
#: Returned by a subscriber with no opinion; the next one is consulted.
NOT_CLAIMED = "not_claimed"

_Subscriber = Callable[[Dict], Awaitable[str]]


class FetchArbiter:
    """Owns ``Fetch.enable``/``Fetch.disable`` for one browser connection."""

    #: Fallback pattern when a subscriber declares none.
    ALL_REQUESTS = {"urlPattern": "*"}

    def __init__(self, browser: Any) -> None:
        self._browser = browser
        # name -> (priority, handler, patterns)
        self._subs: Dict[str, Tuple[int, _Subscriber, List[Dict]]] = {}
        self._enabled = False
        self._lock = asyncio.Lock()

    # -- registration -----------------------------------------------------

    async def register(
        self,
        name: str,
        handler: _Subscriber,
        patterns: Optional[List[Dict]] = None,
        priority: int = 100,
    ) -> None:
        """Add a subscriber and (re-)enable ``Fetch`` with the merged patterns."""
        async with self._lock:
            self._subs[name] = (priority, handler, list(patterns or [self.ALL_REQUESTS]))
            await self._apply_locked()

    async def unregister(self, name: str) -> None:
        """Remove a subscriber.

        ``Fetch.disable`` is only sent once the *last* subscriber leaves --
        the measured global-disable behaviour is exactly the footgun this
        class exists to contain.
        """
        async with self._lock:
            if self._subs.pop(name, None) is None:
                return
            await self._apply_locked()

    def is_registered(self, name: str) -> bool:
        return name in self._subs

    @property
    def active(self) -> bool:
        return self._enabled

    @property
    def subscribers(self) -> Tuple[str, ...]:
        return tuple(sorted(self._subs))

    # -- domain state -----------------------------------------------------

    def merged_patterns(self) -> List[Dict]:
        """Union of every subscriber's patterns, order-stable, de-duplicated.

        A union is required because ``Fetch.enable`` replaces rather than adds:
        re-sending only the newest subscriber's patterns would blind the other.
        """
        merged: List[Dict] = []
        for _prio, _handler, patterns in sorted(self._subs.values(), key=lambda s: s[0]):
            for pattern in patterns:
                if pattern not in merged:
                    merged.append(pattern)
        return merged

    async def _apply_locked(self) -> None:
        if not self._subs:
            if self._enabled:
                try:
                    await self._browser.send("Fetch.disable")
                except Exception as exc:  # pragma: no cover - transport dependent
                    logger.debug("[FetchArbiter] Fetch.disable failed: %s", exc)
                self._browser.off("Fetch.requestPaused", self._on_paused)
                self._enabled = False
            return

        await self._browser.send(
            "Fetch.enable",
            {"patterns": self.merged_patterns(), "handleAuthRequests": False},
        )
        if not self._enabled:
            self._browser.on("Fetch.requestPaused", self._on_paused)
            self._enabled = True

    # -- dispatch ---------------------------------------------------------

    async def _on_paused(self, params: Dict) -> None:
        request_id = params.get("requestId", "")
        for _prio, handler, _patterns in sorted(self._subs.values(), key=lambda s: s[0]):
            try:
                verdict = await handler(params)
            except Exception as exc:
                # Fail closed: a subscriber that blew up has not vouched for
                # this request, so do not let it through on its behalf.
                logger.error("[FetchArbiter] subscriber error, failing request: %s", exc)
                await self._safe(
                    "Fetch.failRequest",
                    {"requestId": request_id, "errorReason": "Failed"},
                )
                return
            if verdict == CLAIMED:
                return

        # Nobody claimed it: this is ordinary traffic and must not be stranded.
        await self._safe("Fetch.continueRequest", {"requestId": request_id})

    async def _safe(self, method: str, params: Dict) -> None:
        try:
            await self._browser.send(method, params)
        except Exception as exc:
            # The request is already gone (navigation cancelled, tab closed).
            logger.debug("[FetchArbiter] %s failed: %s", method, exc)


def get_arbiter(browser: Any) -> FetchArbiter:
    """Return the arbiter for ``browser``, creating it once per connection.

    Attached to the browser object so both subsystems reach the *same* owner
    without a module-level registry that would leak across connections.
    """
    existing = getattr(browser, "_fetch_arbiter", None)
    if existing is None:
        existing = FetchArbiter(browser)
        browser._fetch_arbiter = existing
    return existing


__all__ = ["CLAIMED", "NOT_CLAIMED", "FetchArbiter", "get_arbiter"]
