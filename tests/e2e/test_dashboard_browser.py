"""Live browser E2E for the /gui dashboard.

Why this exists
---------------
The dashboard is 60 JavaScript files and 17k lines. Before this suite, exactly
**two** of those files were ever executed by a test (the two Node harnesses in
tests/test_overview_*_js.py); everything else was checked by reading the source
as text: "does this file exist", "is `.main` balanced in the concatenated
HTML", "does the manifest list what the loader expects". Those tests are
useful, and none of them can tell you that the page actually renders, that
switching a tab shows exactly one panel, or that a broken manifest still
leaves the user with something to look at.

That gap has a history: v4.96.0 shipped a stray `</div>` that pushed six tabs
outside `.main` and produced the "content shifted right with an empty middle"
bug. The guard written afterwards parses HTML — it would not have caught a
purely CSS or JS regression with the same symptom.

What is asserted here is deliberately about *observable behaviour*, not
implementation:

* the page boots with zero console errors, zero page errors, zero failed
  requests;
* every sidebar link switches to exactly one visible panel;
* clicking through all tabs (which fires each tab's `onShow`, and with it its
  API calls) produces no 4xx/5xx and no uncaught exception;
* without a token the dashboard shows a login page and reaches no API;
* when `manifest.json` fails in each of four ways, the documented fail-soft
  still renders the shell AND tells the user on screen -- not only in the
  developer console.

Note on visibility: panels are hidden with `content-visibility:hidden;height:0`
rather than `display:none`, so `offsetParent` stays non-null for hidden tabs.
Measuring height is what actually reflects what a human sees; an early version
of this file used `offsetParent` and reported all 22 panels as visible.
"""
from __future__ import annotations

import json
import os

import pytest

playwright_api = pytest.importorskip(
    "playwright.sync_api", reason="playwright not installed")

pytestmark = pytest.mark.skipif(
    os.environ.get("ARENA_SKIP_BROWSER_E2E") == "1",
    reason="browser E2E disabled via ARENA_SKIP_BROWSER_E2E=1")


def _chromium_available() -> bool:
    """True when a Playwright browser binary is actually installed.

    `pip install playwright` does not download browsers; without
    `playwright install chromium` every test here would fail with a launch
    error that says nothing about the dashboard.
    """
    try:
        with playwright_api.sync_playwright() as p:
            path = p.chromium.executable_path
    except Exception:
        return False
    return bool(path) and os.path.exists(path)


requires_browser = pytest.mark.skipif(
    not _chromium_available(),
    reason="chromium not installed (run: python -m playwright install chromium)")


@pytest.fixture(scope="module")
def browser():
    with playwright_api.sync_playwright() as p:
        b = p.chromium.launch()
        yield b
        b.close()


class Recorder:
    """Collects everything the browser complains about, in one place."""

    def __init__(self, page):
        self.console_errors: list[str] = []
        self.page_errors: list[str] = []
        self.failed_requests: list[str] = []
        self.responses: list[tuple[int, str]] = []
        page.on("console", self._on_console)
        page.on("pageerror", lambda e: self.page_errors.append(str(e)[:300]))
        page.on("requestfailed",
                lambda r: self.failed_requests.append(f"{r.url[-70:]} {r.failure}"))
        page.on("response", lambda r: self.responses.append((r.status, r.url)))

    def _on_console(self, msg) -> None:
        if msg.type == "error":
            self.console_errors.append(msg.text[:300])

    @property
    def clean(self) -> bool:
        return not (self.console_errors or self.page_errors or self.failed_requests)

    def report(self) -> str:
        return json.dumps({
            "console_errors": self.console_errors[:10],
            "page_errors": self.page_errors[:10],
            "failed_requests": self.failed_requests[:10],
        }, indent=2)


def _open_dashboard(browser, bridge, *, token: str | None = "use-real"):
    """Open /gui and wait for the shell to be *rendered*, not for silence.

    v4.165.0: this used `wait_until="networkidle"`, which is the wrong
    condition for this page and produced a flake that only ever fired on
    CI. `networkidle` means 500ms with no network activity, and the
    dashboard polls forever -- `19-auto-refresh.js` every 15s,
    `11-tasks.js` every 10s, `16-audit.js` every 5s when enabled, plus
    per-tab timers in 04d/08b/19/20. On a fast machine the gaps between
    those polls exceed 500ms and the condition happens to be met; on a
    loaded GitHub runner each request takes longer, the gaps close, and
    `page.goto` times out after 45s.

    The evidence it was a race and not a broken page: in the failing run
    the same helper was used by all ten tests and nine of them passed
    (`1 failed, 9 passed in 111.54s`).

    Waiting for `domcontentloaded` plus the element the tests actually
    assert on is both faster and honest -- it asserts the thing we care
    about (the shell rendered) instead of a proxy that a polling page can
    never satisfy.
    """
    page = browser.new_page()
    rec = Recorder(page)
    suffix = f"?token={bridge.token}" if token == "use-real" else ""
    page.goto(f"http://127.0.0.1:{bridge.port}/gui{suffix}",
              wait_until="domcontentloaded", timeout=45_000)
    if token == "use-real":
        # The sidebar is what every caller goes on to query. Without a
        # token the dashboard renders a login page and never builds it,
        # so that path waits for the body instead.
        page.wait_for_selector(".sidebar nav a[data-tab]",
                               state="attached", timeout=45_000)
    else:
        page.wait_for_selector("body", state="attached", timeout=45_000)
    page.wait_for_timeout(1500)
    return page, rec


VISIBLE_PANELS_JS = """() => [...document.querySelectorAll('[id^=tab-]')]
    .filter(e => e.getBoundingClientRect().height > 0)
    .map(e => e.id)"""


@requires_browser
def test_dashboard_boots_without_a_single_error(browser, bridge):
    page, rec = _open_dashboard(browser, bridge)
    try:
        assert "Arena Bridge" in page.title()
        # The whole asset set must load, not just the sync fallback of five.
        assert page.evaluate("document.querySelectorAll('script[src]').length") > 40
        assert page.locator(".sidebar nav a[data-tab]").count() > 0
        assert rec.clean, rec.report()
    finally:
        page.close()


@requires_browser
def test_exactly_one_panel_is_visible_at_boot(browser, bridge):
    page, _ = _open_dashboard(browser, bridge)
    try:
        visible = page.evaluate(VISIBLE_PANELS_JS)
        assert visible == ["tab-overview"], visible
    finally:
        page.close()


@requires_browser
def test_every_tab_switches_to_exactly_one_panel(browser, bridge):
    """The v4.96.0 symptom, checked the way a user would see it."""
    page, rec = _open_dashboard(browser, bridge)
    try:
        links = page.locator(".sidebar nav a[data-tab]")
        count = links.count()
        assert count >= 20, f"only {count} tabs rendered"
        problems = []
        for i in range(count):
            name = links.nth(i).get_attribute("data-tab")
            links.nth(i).click()
            page.wait_for_timeout(250)
            visible = page.evaluate(VISIBLE_PANELS_JS)
            active = page.evaluate(
                "() => (document.querySelector('.sidebar nav a.active') || {})"
                ".getAttribute?.('data-tab')")
            if visible != [f"tab-{name}"] or active != name:
                problems.append({"tab": name, "active": active, "visible": visible})
        assert problems == [], json.dumps(problems, indent=2)
    finally:
        page.close()


@requires_browser
def test_clicking_through_every_tab_raises_nothing(browser, bridge):
    """Each tab's onShow() fires its own API calls; none may fail."""
    page, rec = _open_dashboard(browser, bridge)
    try:
        links = page.locator(".sidebar nav a[data-tab]")
        for i in range(links.count()):
            links.nth(i).click()
            page.wait_for_timeout(600)
        assert rec.page_errors == [], rec.report()
        assert rec.console_errors == [], rec.report()

        bad = [(s, u.split(str(bridge.port))[-1])
               for s, u in rec.responses if s >= 400]
        assert bad == [], f"non-2xx responses while touring the tabs: {bad}"
    finally:
        page.close()


@requires_browser
def test_without_a_token_the_dashboard_shows_login_and_calls_no_api(browser, bridge):
    page, rec = _open_dashboard(browser, bridge, token=None)
    try:
        assert "login" in page.title().lower(), page.title()
        # No tab bodies must exist at all -- not merely be hidden.
        assert page.evaluate("document.querySelectorAll('[id^=tab-]').length") == 0
        api = [u for _, u in rec.responses
               if "/v1/" in u or "/v2/" in u]
        assert api == [], f"login page reached the API: {api}"
    finally:
        page.close()


@pytest.mark.parametrize(("label", "handler_kind"), [
    ("http-500", "status"),
    ("empty-scripts", "empty"),
    ("invalid-json", "junk"),
    ("aborted", "abort"),
])
@requires_browser
def test_broken_manifest_still_renders_the_shell_and_says_so(
        browser, bridge, label, handler_kind):
    """The documented fail-soft, executed instead of read.

    dashboard/index.html retries the manifest three times and then boots from
    a hardcoded five-script list so the user "sees the sidebar and a real
    error message". Both halves are asserted here: the shell renders, AND the
    warning is on the page rather than only in console.warn (a message only a
    developer with devtools open would ever read).
    """
    page = browser.new_page()
    rec = Recorder(page)

    def route(r):
        if handler_kind == "status":
            r.fulfill(status=500, body="boom")
        elif handler_kind == "empty":
            r.fulfill(status=200, content_type="application/json",
                      body='{"scripts": [], "bodies": []}')
        elif handler_kind == "junk":
            r.fulfill(status=200, content_type="application/json",
                      body="not json at all")
        else:
            r.abort()

    page.route("**/gui/assets/manifest.json*", route)
    try:
        page.goto(f"http://127.0.0.1:{bridge.port}/gui?token={bridge.token}",
                  wait_until="load", timeout=45_000)
        page.wait_for_timeout(3500)

        assert page.locator(".sidebar nav a[data-tab]").count() >= 20, \
            f"[{label}] the sidebar did not render from the fallback list"
        assert rec.page_errors == [], f"[{label}] {rec.report()}"

        body_text = page.inner_text("body").lower()
        assert "fallback" in body_text, (
            f"[{label}] fallback mode is invisible to the user; the page said: "
            f"{page.inner_text('body')[:200]!r}")
    finally:
        page.close()


@requires_browser
def test_dashboard_survives_a_reload(browser, bridge):
    """Boot is not idempotent for free: the nav guards on dataset.built."""
    page, rec = _open_dashboard(browser, bridge)
    try:
        # Same reasoning as _open_dashboard: the page polls forever, so
        # "no network for 500ms" is a condition it may never satisfy on a
        # loaded runner. Wait for the sidebar this test is about instead.
        page.reload(wait_until="domcontentloaded", timeout=45_000)
        page.wait_for_selector(".sidebar nav a[data-tab]",
                               state="attached", timeout=45_000)
        page.wait_for_timeout(1500)
        links = page.locator(".sidebar nav a[data-tab]").count()
        assert links >= 20, f"after reload only {links} tabs"
        # A duplicated nav build would double every link.
        assert links == page.evaluate(
            "new Set([...document.querySelectorAll('.sidebar nav a[data-tab]')]"
            ".map(a => a.dataset.tab)).size"), "duplicate sidebar links after reload"
        assert rec.page_errors == [], rec.report()
    finally:
        page.close()
