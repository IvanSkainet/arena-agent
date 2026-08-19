"""Navigation policy: unit behaviour + fail-closed entry-point parity (#103).

The parity half is the point of this file. ``check_navigation`` being correct
is worth little if one of the fifteen call sites that reach ``navigate()``
skips it, so the second half enumerates the agent-facing entry points and
drives each one with the same hostile URLs, asserting both that the request
is refused AND that no navigation reached the browser layer.
"""
from __future__ import annotations

import asyncio
import json
import socket
import sys
from pathlib import Path

import pytest

# The suite has no conftest that puts the repository root on the path, so
# every test module that imports `arena.*` inserts it first and marks the
# imports below E402. The suppressions are bounded to those imports; see the
# same pattern in tests/test_admin_handlers.py and its neighbours.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from arena.browser.cdp.advanced import make_cdp_advanced_handlers  # noqa: E402
from arena.browser.cdp.page import make_cdp_page_handlers  # noqa: E402
from arena.browser.cdp.tabs import make_cdp_tabs_handlers  # noqa: E402
from arena.browser.navigation_policy import (  # noqa: E402
    LOCAL_NAV_ENV,
    NavigationRejected,
    check_navigation,
    local_navigation_allowed,
)


@pytest.fixture(autouse=True)
def _no_real_dns(monkeypatch):
    """Answer every name lookup with a fixed public address.

    The policy resolves hostnames to catch names that point at private space,
    so an unstubbed test would send real DNS traffic from CI and change its
    verdict with the resolver's mood. Tests that care about the DNS branch
    override this with their own stub; everything else gets a deterministic
    public answer. Literal IPs never reach the resolver, so the loopback and
    obfuscation cases are unaffected.
    """
    def fake_getaddrinfo(host, *args, **kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 0))]

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)


# Targets that must never be reachable without the operator opt-in.
HOSTILE_URLS = [
    "http://127.0.0.1:8765/v1/status",
    "http://localhost:9222/json/version",
    "http://169.254.169.254/latest/meta-data/",
    "http://192.168.1.1/admin",
    "http://10.0.0.5/",
    "http://172.16.0.1/",
    "http://[::1]:8765/",
    "http://0.0.0.0:8765/",
    "http://metadata.google.internal/computeMetadata/v1/",
    "http://router.local/",
    "http://backend.internal/secret",
]

# Loopback spellings that a naive string check would let through. These are
# why the policy delegates to the audited `security_ssrf` decoder instead of
# comparing against "127.0.0.1".
OBFUSCATED_LOOPBACK = [
    "http://2130706433/",
    "http://0x7f.1/",
    "http://0177.0.0.1/",
    "http://127.1/",
    "http://[::ffff:127.0.0.1]/",
]

NON_NAVIGABLE_SCHEMES = [
    "file:///etc/passwd",
    "file:///C:/Users/Ivan/AppData/Local/arena/token",
    "data:text/html,<script>fetch('http://127.0.0.1:8765')</script>",
    "javascript:fetch('/v1/status')",
    "chrome://settings/",
    "devtools://devtools/bundled/inspector.html",
    "view-source:http://127.0.0.1:8765/",
    "ftp://example.com/x",
]


# --------------------------------------------------------------------------
# check_navigation
# --------------------------------------------------------------------------

@pytest.mark.parametrize("url", HOSTILE_URLS)
def test_private_and_metadata_targets_are_refused(url):
    with pytest.raises(NavigationRejected) as excinfo:
        check_navigation(url, env={})
    assert LOCAL_NAV_ENV in str(excinfo.value)


@pytest.mark.parametrize("url", OBFUSCATED_LOOPBACK)
def test_obfuscated_loopback_spellings_are_refused(url):
    with pytest.raises(NavigationRejected):
        check_navigation(url, env={})


@pytest.mark.parametrize("url", NON_NAVIGABLE_SCHEMES)
def test_non_http_schemes_are_refused(url):
    with pytest.raises(NavigationRejected) as excinfo:
        check_navigation(url, env={})
    message = str(excinfo.value)
    assert "not allowed for navigation" in message
    # A scheme rejection must not advertise the local-navigation opt-in:
    # ARENA_BROWSER_ALLOW_LOCAL_NAV=1 does not make file:// navigable.
    assert LOCAL_NAV_ENV not in message


@pytest.mark.parametrize("url", NON_NAVIGABLE_SCHEMES)
def test_opt_in_does_not_unlock_non_http_schemes(url):
    with pytest.raises(NavigationRejected):
        check_navigation(url, env={LOCAL_NAV_ENV: "1"})


@pytest.mark.parametrize("url", [
    "https://example.com/",
    "http://example.com/path?q=1",
    "https://sub.domain.example.org:8443/x",
])
def test_public_targets_are_allowed(url):
    assert check_navigation(url, env={}) == url


def test_about_blank_is_allowed_because_new_tabs_default_to_it():
    assert check_navigation("about:blank", env={}) == "about:blank"
    assert check_navigation("  ABOUT:BLANK  ", env={}) == "about:blank"


def test_about_other_than_blank_is_refused():
    for target in ("about:config", "about:settings", "about:"):
        with pytest.raises(NavigationRejected):
            check_navigation(target, env={})


def test_missing_url_keeps_the_original_error_wording():
    for empty in (None, "", "   "):
        with pytest.raises(NavigationRejected) as excinfo:
            check_navigation(empty, env={})
        assert str(excinfo.value) == "missing 'url' parameter"


def test_non_string_url_is_refused():
    for value in (123, ["http://example.com"], {"url": "x"}, True):
        with pytest.raises(NavigationRejected):
            check_navigation(value, env={})


def test_returns_the_url_so_a_dropped_result_cannot_be_a_silent_noop():
    assert check_navigation("https://example.com/a", env={}) == "https://example.com/a"


def test_surrounding_whitespace_is_stripped_before_the_verdict():
    with pytest.raises(NavigationRejected):
        check_navigation("  http://127.0.0.1/  ", env={})


@pytest.mark.parametrize("value", ["1", "true", "TRUE", "yes", "on", " On "])
def test_opt_in_accepts_the_repository_truthy_spellings(value):
    assert local_navigation_allowed({LOCAL_NAV_ENV: value}) is True
    assert check_navigation("http://127.0.0.1:8765/", env={LOCAL_NAV_ENV: value})


@pytest.mark.parametrize("value", ["0", "false", "no", "off", "", "maybe"])
def test_opt_in_rejects_everything_else(value):
    assert local_navigation_allowed({LOCAL_NAV_ENV: value}) is False
    with pytest.raises(NavigationRejected):
        check_navigation("http://127.0.0.1:8765/", env={LOCAL_NAV_ENV: value})


def test_opt_in_defaults_to_off_when_unset():
    assert local_navigation_allowed({}) is False


def test_opt_in_reads_the_process_environment_by_default(monkeypatch):
    monkeypatch.delenv(LOCAL_NAV_ENV, raising=False)
    assert local_navigation_allowed() is False
    with pytest.raises(NavigationRejected):
        check_navigation("http://127.0.0.1:8765/")

    monkeypatch.setenv(LOCAL_NAV_ENV, "1")
    assert local_navigation_allowed() is True
    assert check_navigation("http://127.0.0.1:8765/") == "http://127.0.0.1:8765/"


@pytest.mark.parametrize("url", [
    "http://user:pass@127.0.0.1/",
    "http://user:pass@example.com/",
    "https://token@example.com/x",
    "https://user:@example.com/",
])
def test_credentials_in_url_are_refused(url):
    # `_validate_url` tolerates userinfo, so a public host with credentials
    # used to pass. A navigation hands those credentials to Chromium, which
    # caches them for the origin -- the public transport rejects userinfo for
    # the same reason, and navigation follows the stricter rule.
    with pytest.raises(NavigationRejected):
        check_navigation(url, env={})


@pytest.mark.parametrize("url", [
    "http://user:pass@127.0.0.1/",
    "http://user:pass@example.com/",
])
def test_the_local_opt_in_does_not_unlock_credentials(url):
    with pytest.raises(NavigationRejected) as excinfo:
        check_navigation(url, env={LOCAL_NAV_ENV: "1"})
    assert "credentials" in str(excinfo.value)


def test_malformed_numeric_host_is_refused():
    with pytest.raises(NavigationRejected) as excinfo:
        check_navigation("http://99999999999999/", env={})
    # A malformed address is not unlocked by the opt-in, so the message must
    # not advertise it -- pointing the operator at a flag that will not help
    # is worse than a bare refusal.
    assert LOCAL_NAV_ENV not in str(excinfo.value)


@pytest.mark.parametrize("url,expected", [
    # A host this process cannot parse is a host Chromium may parse
    # differently, so the opt-in must not wave it through: the operator asked
    # to reach a known local service, not to gamble on resolver parity.
    ("http://99999999999999/", "malformed numeric address"),
    ("http://999.999.999.999/", "malformed numeric address"),
    ("http://", "missing host"),
    ("http:///path", "missing host"),
])
def test_the_opt_in_lifts_only_the_private_address_verdicts(url, expected):
    with pytest.raises(NavigationRejected) as excinfo:
        check_navigation(url, env={LOCAL_NAV_ENV: "1"})
    assert expected in str(excinfo.value)


@pytest.mark.parametrize("url", [
    "http://127.0.0.1:8765/v1/status",
    "http://[::1]/",
    "http://0x7f.1/",
])
def test_the_opt_in_does_lift_the_private_address_verdicts(url):
    # Positive control for the test above: if the opt-in stopped working the
    # pair would still pass on refusals alone, hiding a dead flag.
    assert check_navigation(url, env={LOCAL_NAV_ENV: "1"}) == url


def test_the_opt_in_env_var_name_is_the_documented_one():
    # SECURITY.md and the operator runbook name this variable; renaming the
    # constant without updating them would leave the documented flag inert.
    assert LOCAL_NAV_ENV == "ARENA_BROWSER_ALLOW_LOCAL_NAV"


def test_private_refusal_names_the_exact_flag_to_set():
    with pytest.raises(NavigationRejected) as excinfo:
        check_navigation("http://127.0.0.1:8765/", env={})
    message = str(excinfo.value)
    assert message.startswith("private/internal address not allowed")
    assert message.endswith("navigation to private addresses requires "
                            "ARENA_BROWSER_ALLOW_LOCAL_NAV=1")


def test_scheme_refusal_names_the_offending_scheme_and_the_allowed_set():
    with pytest.raises(NavigationRejected) as excinfo:
        check_navigation("file:///etc/passwd", env={})
    assert str(excinfo.value) == (
        "URL scheme 'file' not allowed for navigation "
        "(only http/https, or about:blank)"
    )


def test_scheme_less_target_is_reported_as_none_rather_than_empty_quotes():
    with pytest.raises(NavigationRejected) as excinfo:
        check_navigation("example.com/path", env={})
    assert str(excinfo.value) == (
        "URL scheme '<none>' not allowed for navigation "
        "(only http/https, or about:blank)"
    )


def test_non_string_refusal_says_so_explicitly():
    with pytest.raises(NavigationRejected) as excinfo:
        check_navigation(42, env={})
    assert str(excinfo.value) == "url must be a string"


def test_credentials_refusal_wording_is_exact():
    with pytest.raises(NavigationRejected) as excinfo:
        check_navigation("http://user:pass@example.com/", env={})
    assert str(excinfo.value) == "credentials in URL are not allowed"


def test_unset_variable_defaults_to_empty_not_to_a_truthy_string():
    # `source.get(LOCAL_NAV_ENV, <default>)`: a non-empty default would make
    # the opt-in depend on the fallback rather than on the operator.
    assert local_navigation_allowed({}) is False
    assert local_navigation_allowed({"UNRELATED": "1"}) is False


def test_allowed_scheme_set_is_exactly_http_and_https():
    from arena.browser import navigation_policy as policy

    assert policy.ALLOWED_SCHEMES == frozenset({"http", "https"})
    assert policy.ALLOWED_OPAQUE_TARGETS == frozenset({"about:blank"})


def test_resolving_hostname_verdict_also_offers_the_opt_in():
    from arena.browser import navigation_policy as policy

    for verdict in policy._OPT_IN_LIFTS:
        assert "private" in verdict or "internal" in verdict


def test_a_public_name_resolving_to_loopback_is_refused(monkeypatch):
    """The DNS branch: the name looks public, the answer is 127.0.0.1.

    Resolution is stubbed so the test states the contract instead of
    depending on a third-party wildcard domain still pointing at loopback.
    """
    def fake_getaddrinfo(host, *args, **kwargs):
        assert host == "dev.example.com"
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 0))]

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)

    with pytest.raises(NavigationRejected) as excinfo:
        check_navigation("http://dev.example.com/", env={})
    message = str(excinfo.value)
    assert message.startswith("host resolves to a private/internal address")
    assert LOCAL_NAV_ENV in message


def test_a_public_name_resolving_publicly_is_allowed(monkeypatch):
    def fake_getaddrinfo(host, *args, **kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 0))]

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)

    assert check_navigation("http://example.com/", env={}) == "http://example.com/"


@pytest.mark.parametrize("url", ["http://[oops/", "http://[::1", "https://[::/x"])
def test_unparseable_urls_are_refused_as_invalid(url):
    # `urlparse` raises ValueError on a malformed IPv6 literal; the policy
    # must turn that into a refusal rather than let it escape as a 500.
    with pytest.raises(NavigationRejected) as excinfo:
        check_navigation(url, env={})
    assert str(excinfo.value) == "invalid URL"


@pytest.mark.parametrize("url", ["http://[oops/", "http://[::1"])
def test_unparseable_urls_are_refused_even_with_the_opt_in(url):
    # The credentials parse runs before the opt-in shortcut, so a malformed
    # URL cannot slip through by setting the flag.
    with pytest.raises(NavigationRejected) as excinfo:
        check_navigation(url, env={LOCAL_NAV_ENV: "1"})
    assert str(excinfo.value) == "invalid URL"


# --------------------------------------------------------------------------
# Entry-point parity
# --------------------------------------------------------------------------

class _Tab:
    def __init__(self):
        self.navigated = None
        self.target_id = "tab-1"

    async def navigate(self, url, wait=True, timeout=28):
        self.navigated = (url, wait, timeout)
        return {"frameId": "f"}


class _Browser:
    def __init__(self):
        self.navigated = None

    async def navigate(self, url, wait=True, timeout=None):
        self.navigated = (url, wait, timeout)
        return {"frameId": "f"}

    async def eval_js(self, expr, timeout=None):
        return ""

    async def send(self, method, params=None, timeout=None):
        return {"result": {"data": ""}}


class _Manager:
    def __init__(self, tab):
        self.active_tab = tab
        self.new_tab_url = None

    async def sync_tabs(self):
        return None

    async def new_tab(self, url, activate=True):
        self.new_tab_url = url
        return _NewTab()


class _NewTab:
    target_id = "tab-2"

    def to_dict(self):
        return {"id": self.target_id}


class _Response:
    def __init__(self, payload, status):
        self.payload = payload
        self.status = status


class _Request:
    def __init__(self, body):
        self._body = body

    async def json(self):
        if isinstance(self._body, Exception):
            raise self._body
        return self._body


def _make_ctx(kind, tab, browser):
    """Build the handler context each factory expects."""
    from arena.contexts.cdp import (
        CdpAdvancedHandlerContext,
        CdpPageHandlerContext,
        CdpTabsHandlerContext,
    )

    manager = _Manager(tab)
    state = {"connected": True, "manager": manager, "last_navigation_time": 0}

    async def active_tab(tab_id=None):
        return tab, None

    common = {
        "require_auth": lambda request: None,
        "record_request": lambda **kwargs: None,
        "cors_json_response": lambda payload, status=200: _Response(payload, status),
        "cdp_state": state,
        "log_debug": lambda *a, **k: None,
    }
    if kind == "page":
        return CdpPageHandlerContext(
            **common,
            cdp_active_tab=active_tab,
            default_max_output=10000,
            log_warning=lambda *a, **k: None,
            log_error=lambda *a, **k: None,
        ), manager
    if kind == "tabs":
        return CdpTabsHandlerContext(**common), manager
    return CdpAdvancedHandlerContext(
        require_auth=common["require_auth"],
        record_request=common["record_request"],
        cors_json_response=common["cors_json_response"],
        cdp_state=state,
        ensure_cookie_manager=lambda: None,
        watcher_active=lambda: False,
        bridge_start_time=0.0,
    ), manager


def _call(handler, body):
    return asyncio.run(handler(_Request(body)))


def _payload(response):
    payload = response.payload
    return json.loads(payload) if isinstance(payload, str) else payload


@pytest.fixture(autouse=True)
def _no_local_opt_in(monkeypatch):
    monkeypatch.delenv(LOCAL_NAV_ENV, raising=False)


@pytest.mark.parametrize("url", HOSTILE_URLS[:6] + NON_NAVIGABLE_SCHEMES[:4])
def test_cdp_navigate_endpoint_refuses_without_touching_the_browser(url):
    tab = _Tab()
    ctx, _mgr = _make_ctx("page", tab, _Browser())
    handler = make_cdp_page_handlers(ctx).navigate

    response = _call(handler, {"url": url})

    assert response.status == 400
    assert _payload(response)["ok"] is False
    assert tab.navigated is None, "Page.navigate was reached despite rejection"


@pytest.mark.parametrize("url", HOSTILE_URLS[:4] + NON_NAVIGABLE_SCHEMES[:2])
def test_cdp_tabs_new_refuses_without_opening_a_tab(url):
    tab = _Tab()
    ctx, manager = _make_ctx("tabs", tab, _Browser())
    handler = make_cdp_tabs_handlers(ctx).new

    response = _call(handler, {"url": url})

    assert response.status == 400
    assert manager.new_tab_url is None, "a tab was opened despite rejection"


def test_cdp_tabs_new_still_defaults_to_about_blank():
    tab = _Tab()
    ctx, manager = _make_ctx("tabs", tab, _Browser())
    handler = make_cdp_tabs_handlers(ctx).new

    response = _call(handler, {})

    assert response.status == 200
    assert manager.new_tab_url == "about:blank"


@pytest.mark.parametrize("handler_name", ["stealth_extract", "stealth_shot"])
@pytest.mark.parametrize("url", [
    "http://127.0.0.1:8765/v1/status",
    "http://169.254.169.254/latest/meta-data/",
    "file:///etc/passwd",
])
def test_stealth_endpoints_refuse_without_touching_the_browser(handler_name, url):
    from arena.browser.cdp import advanced_common

    browser = _Browser()
    tab = _Tab()
    ctx, _mgr = _make_ctx("advanced", tab, browser)
    handlers = make_cdp_advanced_handlers(ctx)
    handler = getattr(handlers, handler_name)

    response = _call(handler, {"url": url})

    assert response.status == 400
    assert _payload(response)["ok"] is False
    assert browser.navigated is None, "the stealth path navigated despite rejection"
    assert advanced_common is not None


def test_cdp_navigate_still_allows_a_public_url():
    tab = _Tab()
    ctx, _mgr = _make_ctx("page", tab, _Browser())
    handler = make_cdp_page_handlers(ctx).navigate

    response = _call(handler, {"url": "https://example.com/", "wait": False})

    assert response.status == 200
    assert tab.navigated == ("https://example.com/", False, 28)


def test_cdp_navigate_honours_the_operator_opt_in(monkeypatch):
    monkeypatch.setenv(LOCAL_NAV_ENV, "1")
    tab = _Tab()
    ctx, _mgr = _make_ctx("page", tab, _Browser())
    handler = make_cdp_page_handlers(ctx).navigate

    response = _call(handler, {"url": "http://127.0.0.1:8765/gui", "wait": False})

    assert response.status == 200
    assert tab.navigated is not None, "the opt-in did not reach the browser"
    assert tab.navigated[0] == "http://127.0.0.1:8765/gui"


def test_profile_restore_skips_rejected_tabs_but_keeps_the_good_ones():
    from arena.profiles.load_handler import _restore_tabs

    tab = _Tab()
    navigated = []

    class _RecordingTab:
        async def navigate(self, url, wait=True, timeout=None):
            navigated.append(url)
            return {}

    class _Ctx:
        async def cdp_active_tab(self, tab_id=None):
            return _RecordingTab(), None

    restored = asyncio.run(_restore_tabs(_Ctx(), [
        {"url": "https://example.com/a"},
        {"url": "http://127.0.0.1:8765/v1/status"},
        {"url": "file:///etc/passwd"},
        {"url": "https://example.org/b"},
    ]))

    assert restored == 2
    assert navigated == ["https://example.com/a", "https://example.org/b"]
    assert tab.navigated is None


def test_browser_launch_tool_refuses_a_hostile_url():
    from arena.mcp import tool_browser_headed as headed

    result = headed._launch({"url": "file:///etc/shadow", "session": "policy-test"})

    assert result["ok"] is False
    assert "not allowed for navigation" in result["error"]
