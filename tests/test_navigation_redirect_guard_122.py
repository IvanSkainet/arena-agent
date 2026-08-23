"""#122: the navigation policy must survive an HTTP redirect.

``check_navigation()`` judged the URL the agent supplied. Chromium then
followed redirects inside its own network stack and a 30x never re-entered the
policy, so this was reachable:

    agent   -> https://public.example/r      (allowed: public, https)
    server  -> 302 Location: http://127.0.0.1:8765/v1/status
    Chromium-> navigates. No second check. Loopback reached.

Demonstrated end to end on live Chromium before any code was written: a real
public ``https://`` start URL, accepted by the static policy, redirected to a
loopback HTTP server, and the secret served there was read back out of the
DOM (``SECRET LEAKED: True``). The same probe with the guard armed refuses the
redirect target.

Three facts about the CDP ``Fetch`` domain were measured on live Chromium
rather than assumed, because the design depends on all three:

1. a second ``Fetch.enable`` **replaces** the first one's patterns -- so two
   subsystems cannot each own the domain;
2. ``Fetch.disable`` is **global** -- so the interceptor's ``stop()`` would
   have silently disarmed this guard;
3. a redirect target arrives as its **own** ``Fetch.requestPaused`` with
   ``resourceType == "Document"`` and the main frame's ``frameId`` -- which is
   what makes per-navigation enforcement possible at all.

Fact 2 is why ``FetchArbiter`` exists and why the interceptor was moved onto
it in the same change: without arbitration, "interception is on" and "the
guard is armed" are one bit of state with two owners.
"""

from __future__ import annotations

import asyncio
import pathlib

import pytest

from arena.browser.cdp_client.fetch_arbiter import CLAIMED, NOT_CLAIMED, get_arbiter
from arena.browser.cdp_client.interceptor import CDPNetworkInterceptor
from arena.browser.cdp_client.navigation_guard import (
    GUARD_NAME,
    GUARD_PRIORITY,
    arm_navigation_guard,
    disarm_navigation_guard,
)

MAIN_FRAME = "MAIN-FRAME-ID"


class FakeBrowser:
    """Scripted CDP transport: records what would go over the wire."""

    def __init__(self, root: str = MAIN_FRAME) -> None:
        self.sent: list[tuple[str, dict]] = []
        self._handlers: dict[str, list] = {}
        self.root = root
        self.frame_tree_calls = 0

    def on(self, event, cb):
        self._handlers.setdefault(event, []).append(cb)

    def off(self, event, cb):
        if cb in self._handlers.get(event, []):
            self._handlers[event].remove(cb)

    async def send(self, method, params=None, timeout=None):
        self.sent.append((method, params or {}))
        if method == "Page.getFrameTree":
            self.frame_tree_calls += 1
            return {"result": {"frameTree": {"frame": {"id": self.root}}}}
        return {"result": {}}

    async def fire(self, params):
        for cb in list(self._handlers.get("Fetch.requestPaused", [])):
            result = cb(params)
            if asyncio.iscoroutine(result):
                await result

    def fetch_calls(self):
        return [(m, p) for m, p in self.sent if m.startswith("Fetch.")]

    def verdict(self):
        """The single disposition applied to the last paused request."""
        calls = [m for m, _ in self.fetch_calls() if m in
                 {"Fetch.failRequest", "Fetch.continueRequest", "Fetch.fulfillRequest"}]
        return calls


def paused(url, *, rtype="Document", frame=MAIN_FRAME, rid="REQ-1"):
    return {"requestId": rid, "resourceType": rtype, "frameId": frame,
            "request": {"url": url, "method": "GET", "headers": {}}}


@pytest.fixture
def browser():
    return FakeBrowser()


# --- the bug itself --------------------------------------------------------

@pytest.mark.parametrize("target", [
    "http://127.0.0.1:8765/v1/status",       # the bridge's own API
    "http://169.254.169.254/latest/meta-data/",  # cloud metadata
    "http://192.168.0.1/",                   # LAN device
    "http://[::1]:8765/",                    # loopback, IPv6
])
def test_redirect_to_a_private_target_is_failed(browser, target):
    asyncio.run(_redirect_case(browser, target))


async def _redirect_case(browser, target):
    await arm_navigation_guard(browser, env={})
    browser.sent.clear()
    await browser.fire(paused(target))
    calls = browser.fetch_calls()
    assert calls, f"{target} produced no disposition at all"
    method, params = calls[0]
    assert method == "Fetch.failRequest", f"{target} was not blocked: {calls}"
    assert params.get("errorReason") == "BlockedByClient"


def test_public_redirect_target_is_allowed_through(browser):
    """The guard must not break ordinary browsing."""
    async def go():
        await arm_navigation_guard(browser, env={})
        browser.sent.clear()
        await browser.fire(paused("https://example.com/page"))
        assert browser.verdict() == ["Fetch.continueRequest"]
    asyncio.run(go())


def test_error_text_matches_the_static_policy(browser):
    """"The same error strings as the static policy; no second policy module."""
    async def go():
        guard = await arm_navigation_guard(browser, env={})
        await browser.fire(paused("http://127.0.0.1:8765/x"))
        assert guard.rejections, "no rejection recorded"
        _url, message = guard.rejections[0]
        assert "private/internal address not allowed" in message
        assert "ARENA_BROWSER_ALLOW_LOCAL_NAV" in message
    asyncio.run(go())


# --- scope: what must NOT be judged ---------------------------------------

def test_subframe_navigation_is_not_judged(browser):
    """Only the top frame is a navigation in the sense the policy is about."""
    async def go():
        await arm_navigation_guard(browser, env={})
        browser.sent.clear()
        await browser.fire(paused("http://127.0.0.1:9/x", frame="SUBFRAME-ID"))
        assert browser.verdict() == ["Fetch.continueRequest"]
    asyncio.run(go())


@pytest.mark.parametrize("rtype", ["Image", "XHR", "Script", "Stylesheet", "Fetch"])
def test_subresources_are_not_judged(browser, rtype):
    """Blocking these would break ordinary pages for no navigation gain."""
    async def go():
        await arm_navigation_guard(browser, env={})
        browser.sent.clear()
        await browser.fire(paused("http://127.0.0.1:9/asset", rtype=rtype))
        assert browser.verdict() == ["Fetch.continueRequest"]
    asyncio.run(go())


def test_operator_opt_in_carries_across_the_redirect(browser):
    """An operator who opted into local navigation keeps it after a 30x."""
    async def go():
        await arm_navigation_guard(browser, env={"ARENA_BROWSER_ALLOW_LOCAL_NAV": "1"})
        browser.sent.clear()
        await browser.fire(paused("http://127.0.0.1:8765/v1/status"))
        assert browser.verdict() == ["Fetch.continueRequest"]
    asyncio.run(go())


# --- Fetch ownership, the part the issue asked to resolve explicitly -------

def test_interceptor_stop_does_not_disarm_the_guard(browser):
    """Measured: Fetch.disable is global. Without arbitration this was fatal.

    The interceptor stopping is a routine user action; it must not silently
    remove the SSRF guard from every later navigation.
    """
    async def go():
        await arm_navigation_guard(browser, env={})
        interceptor = CDPNetworkInterceptor(browser)
        await interceptor.start()
        assert set(get_arbiter(browser).subscribers) == {GUARD_NAME, "network_interceptor"}

        await interceptor.stop()
        assert get_arbiter(browser).subscribers == (GUARD_NAME,)
        assert not any(m == "Fetch.disable" for m, _ in browser.sent), \
            "Fetch.disable was sent while the guard still needed the domain"

        browser.sent.clear()
        await browser.fire(paused("http://169.254.169.254/latest/meta-data/"))
        assert browser.verdict() == ["Fetch.failRequest"]
    asyncio.run(go())


def test_both_subsystems_active_at_once(browser):
    """The issue's explicit requirement: a test for both active together."""
    async def go():
        await arm_navigation_guard(browser, env={})
        interceptor = CDPNetworkInterceptor(browser)
        await interceptor.start(patterns=[{"urlPattern": "*://tracked.example/*"}])

        # Guard still blocks a private document...
        browser.sent.clear()
        await browser.fire(paused("http://127.0.0.1:8765/v1/status"))
        assert browser.verdict() == ["Fetch.failRequest"]

        # ...while unrelated traffic is continued exactly once.
        browser.sent.clear()
        await browser.fire(paused("https://example.com/asset.png", rtype="Image"))
        assert browser.verdict() == ["Fetch.continueRequest"]
    asyncio.run(go())


def test_guard_runs_before_user_rules(browser):
    """A user rule must not be able to launder a request past the policy."""
    assert GUARD_PRIORITY < 100, "guard must sort ahead of the interceptor"

    async def go():
        arbiter = get_arbiter(browser)
        await arm_navigation_guard(browser, env={})

        seen: list[str] = []

        async def greedy(_params):
            seen.append("user-rule")
            return CLAIMED       # would swallow everything if consulted first

        await arbiter.register("greedy", greedy, priority=50)
        await browser.fire(paused("http://127.0.0.1:8765/v1/status"))
        assert seen == [], "a user rule was consulted before the SSRF guard"
    asyncio.run(go())


def test_disable_is_sent_only_when_the_last_subscriber_leaves(browser):
    async def go():
        await arm_navigation_guard(browser, env={})
        interceptor = CDPNetworkInterceptor(browser)
        await interceptor.start()
        await interceptor.stop()
        assert not any(m == "Fetch.disable" for m, _ in browser.sent)

        await disarm_navigation_guard(browser)
        assert any(m == "Fetch.disable" for m, _ in browser.sent), \
            "Fetch was left enabled with no subscribers"
        assert get_arbiter(browser).subscribers == ()
    asyncio.run(go())


def test_enable_carries_the_union_of_patterns(browser):
    """Fetch.enable replaces rather than adds, so the arbiter must merge."""
    async def go():
        arbiter = get_arbiter(browser)
        await arbiter.register("a", _noop, patterns=[{"urlPattern": "*://a.example/*"}])
        await arbiter.register("b", _noop, patterns=[{"urlPattern": "*://b.example/*"}])
        last = [p for m, p in browser.sent if m == "Fetch.enable"][-1]
        assert {"urlPattern": "*://a.example/*"} in last["patterns"]
        assert {"urlPattern": "*://b.example/*"} in last["patterns"], \
            "the earlier subscriber's patterns were dropped"
    asyncio.run(go())


async def _noop(_params):
    return NOT_CLAIMED


# --- fail-closed behaviour -------------------------------------------------

def test_a_crashing_subscriber_fails_the_request(browser):
    """A guard that raised has not vouched for the request."""
    async def go():
        arbiter = get_arbiter(browser)

        async def boom(_params):
            raise RuntimeError("guard exploded")

        await arbiter.register("boom", boom, priority=0)
        browser.sent.clear()
        await browser.fire(paused("https://example.com/"))
        assert browser.verdict() == ["Fetch.failRequest"], \
            "a crashed subscriber let the request through"
    asyncio.run(go())


def test_unclaimed_requests_are_continued_not_stranded(browser):
    """A missed continueRequest hangs the page rather than blocking it."""
    async def go():
        arbiter = get_arbiter(browser)
        await arbiter.register("quiet", _noop)
        browser.sent.clear()
        await browser.fire(paused("https://example.com/", rtype="Image"))
        assert browser.verdict() == ["Fetch.continueRequest"]
    asyncio.run(go())


def test_exactly_one_disposition_per_request(browser):
    """Continue-twice is a CDP protocol error; claim must stop the chain."""
    async def go():
        await arm_navigation_guard(browser, env={})
        interceptor = CDPNetworkInterceptor(browser)
        await interceptor.start()
        browser.sent.clear()
        await browser.fire(paused("http://127.0.0.1:8765/v1/status"))
        assert len(browser.verdict()) == 1, f"multiple dispositions: {browser.verdict()}"
    asyncio.run(go())


def test_arming_is_idempotent(browser):
    """Every navigation arms the guard; that must not stack subscribers."""
    async def go():
        await arm_navigation_guard(browser, env={})
        await arm_navigation_guard(browser, env={})
        await arm_navigation_guard(browser, env={})
        assert get_arbiter(browser).subscribers == (GUARD_NAME,)
    asyncio.run(go())


def test_frame_tree_is_resolved_once(browser):
    """The main frame id is cached; not a round trip per request."""
    async def go():
        await arm_navigation_guard(browser, env={})
        for i in range(3):
            await browser.fire(paused("https://example.com/", rid=f"R{i}"))
        assert browser.frame_tree_calls <= 1
    asyncio.run(go())


def test_non_cdp_screenshot_paths_are_documented_as_uncovered():
    """The issue requires a recorded decision for the non-CDP shot paths.

    `browser.shot` runs `chromium --headless --screenshot <url>` with no CDP
    session, so there is no `Fetch` domain to arm and this guard cannot reach
    it. `--host-resolver-rules` was evaluated as an alternative and rejected:
    it rewrites *name* resolution, while the demonstrated attack redirects to
    a literal IP, which bypasses name resolution entirely. An attempt to
    measure it produced an empty DOM in both the ruled and control runs, so
    it is recorded here as unproven rather than claimed either way.

    Those paths keep the static `check_navigation()` check on the URL the
    agent supplies -- the same protection they had before this change, no
    worse -- and the redirect gap for them stays open and documented in
    SECURITY.md. This test exists so the gap cannot be quietly forgotten:
    it fails if SECURITY.md stops saying so.
    """
    from pathlib import Path

    security = (Path(__file__).resolve().parents[1] / "SECURITY.md").read_text(encoding="utf-8")
    assert "browser.shot" in security, "SECURITY.md no longer records the shot-path gap"
    assert "--headless" in security or "headless" in security


# --- defects found in review of PR #173 ------------------------------------

def test_interception_rule_cannot_launder_navigation_to_a_private_target(browser):
    """A redirect rule is a navigation the agent chose; it faces the policy.

    The guard judges the URL of the paused request. An interception rule then
    rewrites that request via `Fetch.continueRequest{url}`, so an allowed
    public target can be swapped for loopback after the guard has passed it.
    Reproduced against the first revision of this branch: a rule matching
    "example.com" rewrote to http://127.0.0.1:8765/v1/status and the request
    went through.
    """
    from arena.browser.cdp_client.intercept_rule import InterceptRule

    async def go():
        await arm_navigation_guard(browser, env={})
        interceptor = CDPNetworkInterceptor(browser)
        await interceptor.start()
        interceptor.add_rule(InterceptRule(
            name="launder", url_pattern="example.com", action="redirect",
            redirect_url="http://127.0.0.1:8765/v1/status",
        ))
        browser.sent.clear()
        await browser.fire(paused("https://example.com/ok"))

        assert browser.verdict() == ["Fetch.failRequest"]
        rewrites = [p.get("url") for m, p in browser.fetch_calls()
                    if m == "Fetch.continueRequest"]
        assert "http://127.0.0.1:8765/v1/status" not in rewrites

    asyncio.run(go())


def test_a_rule_may_still_rewrite_to_a_public_target(browser):
    """The fix must not break ordinary redirect rules."""
    from arena.browser.cdp_client.intercept_rule import InterceptRule

    async def go():
        await arm_navigation_guard(browser, env={})
        interceptor = CDPNetworkInterceptor(browser)
        await interceptor.start()
        interceptor.add_rule(InterceptRule(
            name="mirror", url_pattern="example.com", action="redirect",
            redirect_url="https://mirror.example.org/ok",
        ))
        browser.sent.clear()
        await browser.fire(paused("https://example.com/ok"))

        assert [(m, p.get("url")) for m, p in browser.fetch_calls()] == [
            ("Fetch.continueRequest", "https://mirror.example.org/ok")
        ]

    asyncio.run(go())


def test_guard_survives_a_reconnect(browser):
    """A new CDP session starts with Fetch disabled.

    The arbiter still believed the domain was enabled, so nothing paused and
    the guard stopped enforcing without a sound.
    """
    async def go():
        await arm_navigation_guard(browser, env={})
        arbiter = get_arbiter(browser)
        browser.sent.clear()

        await arbiter.resync()
        assert "Fetch.enable" in [m for m, _ in browser.sent]

        # exactly one listener, so a paused request gets one disposition
        browser.sent.clear()
        await browser.fire(paused("http://127.0.0.1:8765/v1/status"))
        assert browser.verdict() == ["Fetch.failRequest"]

    asyncio.run(go())


def test_reconnect_resync_is_wired_into_the_browser():
    """The arbiter is resynced by reconnect() itself, not only on demand."""
    source = pathlib.Path("arena/browser/cdp_client/browser.py").read_text(encoding="utf-8")
    reconnect = source.split("async def reconnect", 1)[1]
    assert "resync()" in reconnect, "reconnect() must replay the Fetch domain state"


def test_a_stale_main_frame_id_does_not_excuse_a_navigation(browser):
    """The cached frame id survives target switches.

    A stale id makes a genuine top-level navigation look like a subframe, and
    subframes are skipped -- unchecked, fail-open. A mismatch must force a
    re-read of the frame tree before the request is excused.
    """
    async def go():
        await arm_navigation_guard(browser, env={})
        await browser.fire(paused("https://example.com/", rid="WARM"))

        browser.root = "NEW-FRAME-AFTER-NAVIGATION"
        browser.sent.clear()
        await browser.fire(paused("http://127.0.0.1:8765/v1/status",
                                  frame="NEW-FRAME-AFTER-NAVIGATION", rid="R2"))

        assert browser.verdict() == ["Fetch.failRequest"]

    asyncio.run(go())
