"""Navigation policy tests for #103 (CDP navigate had no SSRF validation).

Two layers are covered:

* the policy itself, as a pure function;
* parity across the agent-facing entry points, so a URL refused by one is
  refused by all of them. The parity suite is the point of the issue -- the
  defect was never "this one function is wrong", it was "the decision was
  applied to one path out of six".
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from arena.browser.navigation_policy import (  # noqa: E402
    ALLOWED_SCHEMES,
    BLANK_URL,
    ERROR_EMPTY,
    ERROR_INTERNAL_HOST,
    ERROR_INVALID,
    ERROR_MALFORMED_NUMERIC,
    ERROR_NO_HOST,
    ERROR_PRIVATE,
    ERROR_RESOLVED_PRIVATE,
    LOCAL_NAVIGATION_ENV,
    NavigationRejected,
    local_navigation_allowed,
    navigation_error,
)

# Targets the issue names explicitly, plus the obfuscated loopback spellings
# `security_ssrf` already knew how to decode.
BLOCKED_URLS = [
    "http://127.0.0.1:8765/v1/status",
    "http://127.0.0.1:9222/json",
    "http://localhost:8765/v1/status",
    "http://[::1]:8765/",
    "http://169.254.169.254/latest/meta-data/",
    "http://metadata.google.internal/computeMetadata/v1/",
    "http://192.168.1.1/admin",
    "http://10.0.0.5/",
    "http://172.16.0.1/",
    "http://2130706433/",
    "http://0x7f.1/",
    "http://0177.1/",
    "http://127.1/",
    "file:///etc/passwd",
    "file:///C:/Windows/win.ini",
    "data:text/html,<script>alert(1)</script>",
    "javascript:alert(document.cookie)",
    "chrome://settings",
    "devtools://devtools/bundled/inspector.html",
    "view-source:http://127.0.0.1:8765/",
]

ALLOWED_URLS = [
    "https://example.com/",
    "http://example.com/path?q=1",
    "https://sub.domain.example.org:8443/x",
]


class _Recorder:
    """Minimal stand-in for the handler context surface these handlers use."""

    def __init__(self):
        self.errors = 0
        self.warnings = []

    def record_request(self, *_args, **_kwargs):
        self.errors += 1

    def cors_json_response(self, payload, status=200):
        return {"payload": payload, "status": status}

    def log_debug(self, *_a, **_k):
        pass

    def log_warning(self, fmt, *args):
        self.warnings.append(fmt % args if args else fmt)

    def log_error(self, *_a, **_k):
        pass


class _Request:
    def __init__(self, body):
        self._body = body

    async def json(self):
        return self._body


# --------------------------------------------------------------------------
# The policy
# --------------------------------------------------------------------------

@pytest.mark.parametrize("url", BLOCKED_URLS)
def test_policy_rejects_blocked_targets(url):
    assert navigation_error(url) is not None


@pytest.mark.parametrize("url", ALLOWED_URLS)
def test_policy_allows_public_http_targets(url):
    assert navigation_error(url) is None


def test_policy_allows_about_blank_only_as_exact_match():
    assert navigation_error(BLANK_URL) is None
    assert navigation_error("ABOUT:BLANK") is None
    assert navigation_error("  about:blank  ") is None
    assert navigation_error("about:cache") is not None
    assert navigation_error("about:net-internals") is not None
    assert navigation_error("about:blank#x") is not None


def test_policy_can_forbid_blank():
    assert navigation_error(BLANK_URL, allow_blank=False) is not None


@pytest.mark.parametrize("value", ["", "   ", None, 42, [], {}])
def test_policy_rejects_non_string_and_empty(value):
    assert navigation_error(value) == ERROR_EMPTY


def test_policy_reports_scheme_in_the_error():
    error = navigation_error("file:///etc/passwd")
    assert "file" in error
    assert "http/https" in error


def test_policy_rejects_url_without_host():
    assert navigation_error("http:///path") == ERROR_NO_HOST


def test_policy_rejects_malformed_numeric_host():
    assert navigation_error("http://99999999999999/") == ERROR_MALFORMED_NUMERIC


@pytest.mark.parametrize("host,expected", [
    ("app.localhost", ERROR_INTERNAL_HOST),
    ("box.localdomain", ERROR_INTERNAL_HOST),
    ("db.internal", ERROR_INTERNAL_HOST),
    ("printer.local", ERROR_INTERNAL_HOST),
    ("localhost", ERROR_INTERNAL_HOST),
    ("localhost.localdomain", ERROR_INTERNAL_HOST),
    ("metadata", ERROR_INTERNAL_HOST),
    ("metadata.google.internal", ERROR_INTERNAL_HOST),
])
def test_policy_rejects_each_internal_hostname_suffix(host, expected):
    assert navigation_error(f"http://{host}/") == expected


def test_policy_error_texts_are_exact():
    """The strings are a contract: the dashboard and these tests match them.

    Asserted against literals rather than against the constants they come
    from. Comparing `navigation_error(...) == ERROR_NO_HOST` passes happily
    when *both* are None, so a constant blanked by accident would read as
    green -- mutation testing caught exactly that.
    """
    assert navigation_error("http://127.0.0.1/") == (
        "private/internal address not allowed for navigation "
        "(set ARENA_BROWSER_ALLOW_LOCAL_NAVIGATION=1 to permit local targets)"
    )
    assert navigation_error("http://localhost/") == "internal/metadata hostname not allowed"
    assert navigation_error("http://99999999999999/") == "malformed numeric address not allowed"
    assert navigation_error("http:///p") == "missing host"
    assert navigation_error("") == "missing 'url' parameter"
    assert navigation_error("file:///x") == (
        "URL scheme 'file' not allowed for navigation (only http/https)"
    )


def test_policy_error_constants_are_non_empty_strings():
    """Every exported message must actually carry text."""
    for name, value in [
        ("ERROR_EMPTY", ERROR_EMPTY),
        ("ERROR_INVALID", ERROR_INVALID),
        ("ERROR_NO_HOST", ERROR_NO_HOST),
        ("ERROR_INTERNAL_HOST", ERROR_INTERNAL_HOST),
        ("ERROR_PRIVATE", ERROR_PRIVATE),
        ("ERROR_MALFORMED_NUMERIC", ERROR_MALFORMED_NUMERIC),
        ("ERROR_RESOLVED_PRIVATE", ERROR_RESOLVED_PRIVATE),
    ]:
        assert isinstance(value, str) and value.strip(), name


def test_invalid_url_error_is_reachable_and_worded():
    """An unterminated IPv6 literal makes `urlparse` itself raise."""
    assert navigation_error("http://[::1") == "invalid URL"


@pytest.mark.parametrize("url", [
    r"http://127.0.0.1\@evil.com/",
    r"http://evil.com\.127.0.0.1/",
    r"http:\\127.0.0.1/",
    r"http://evil.com/..\@127.0.0.1",
])
def test_backslash_urls_are_refused_as_parser_differentials(url):
    """Chromium reads `\\` as a path separator; `urlparse` does not.

    `http://127.0.0.1\\@evil.com/` parses to host `evil.com` in Python and to
    host `127.0.0.1` in Chromium, so approving it on Python's reading would
    validate one host and navigate to another.
    """
    assert navigation_error(url) is not None


@pytest.mark.parametrize("url", [
    "http://ex\tample.com/",
    "http://ex\nample.com/",
    "http://ex\rample.com/",
    "http://exa mple.com/",
    "http://example.com/\x00",
])
def test_whitespace_and_control_characters_are_refused(url):
    """Chromium strips these before parsing; `urlparse` keeps them."""
    assert navigation_error(url) == "invalid URL"


@pytest.mark.parametrize("url", [
    "https://example.com/a%20b",
    "https://example.com/?q=a+b",
    "https://example.com/path/to/page#frag",
    "https://user.example.com:8443/x?y=1&z=2",
])
def test_legitimate_urls_survive_the_differential_checks(url):
    """Percent-encoding and query syntax must not be caught by the above."""
    assert navigation_error(url) is None


def test_resolved_private_error_text_is_exact(monkeypatch):
    monkeypatch.setattr(
        "arena.browser.navigation_policy.socket.getaddrinfo",
        lambda *_a, **_k: [(2, 1, 6, "", ("127.0.0.1", 0))],
    )
    assert navigation_error("http://localtest.me/") == (
        "host resolves to a private/internal address "
        "(set ARENA_BROWSER_ALLOW_LOCAL_NAVIGATION=1 to permit local targets)"
    )


def test_policy_env_var_name_is_stable():
    """Renaming the opt-in silently would strand every documented runbook."""
    assert LOCAL_NAVIGATION_ENV == "ARENA_BROWSER_ALLOW_LOCAL_NAVIGATION"


def test_policy_strips_only_trailing_dots_from_host():
    """A fully-qualified `localhost.` is the same host as `localhost`."""
    assert navigation_error("http://localhost./") == ERROR_INTERNAL_HOST
    assert navigation_error("http://127.0.0.1./") == ERROR_PRIVATE


def test_policy_error_mentions_the_optin_for_private_targets():
    assert LOCAL_NAVIGATION_ENV in navigation_error("http://127.0.0.1/")
    assert LOCAL_NAVIGATION_ENV in ERROR_PRIVATE
    assert LOCAL_NAVIGATION_ENV in ERROR_RESOLVED_PRIVATE


def test_allowed_schemes_are_exactly_http_and_https():
    assert ALLOWED_SCHEMES == ("http", "https")


@pytest.mark.parametrize("scheme", [
    "file", "data", "javascript", "chrome", "chrome-extension", "devtools",
    "view-source", "blob", "ftp", "ws", "wss", "about", "filesystem", "content",
])
def test_policy_rejects_every_non_web_scheme(scheme):
    """An allowlist, so a scheme Chromium grows tomorrow is refused today."""
    error = navigation_error(f"{scheme}://host/path")
    assert error is not None
    assert scheme in error


@pytest.mark.parametrize("url", [
    "FILE:///etc/passwd",
    "JavaScript:alert(1)",
    "ChRoMe://settings",
])
def test_policy_scheme_check_is_case_insensitive(url):
    assert navigation_error(url) is not None


def test_policy_rejects_file_scheme_on_every_surface():
    """`file://` is the target that turns navigation into local file read."""
    for url in ("file:///etc/shadow", "file:///C:/Users/Ivan/.ssh/id_rsa", "file://localhost/etc/passwd"):
        assert navigation_error(url) is not None, url


# --------------------------------------------------------------------------
# The opt-in
# --------------------------------------------------------------------------

@pytest.mark.parametrize("value", ["1", "true", "TRUE", "yes", " yes "])
def test_optin_accepts_truthy_spellings(value):
    assert local_navigation_allowed({LOCAL_NAVIGATION_ENV: value}) is True


@pytest.mark.parametrize("value", ["", "0", "no", "false", "maybe"])
def test_optin_rejects_other_values(value):
    assert local_navigation_allowed({LOCAL_NAVIGATION_ENV: value}) is False


def test_optin_absent_by_default():
    assert local_navigation_allowed({}) is False


@pytest.mark.parametrize("url", [
    "http://127.0.0.1:3000/",
    "http://localhost:3000/app",
    "http://192.168.1.10/",
])
def test_optin_permits_local_navigation(url):
    env = {LOCAL_NAVIGATION_ENV: "1"}
    assert navigation_error(url) is not None
    assert navigation_error(url, env=env) is None


@pytest.mark.parametrize("url", [
    "file:///etc/passwd",
    "javascript:alert(1)",
    "data:text/html,x",
    "chrome://settings",
])
def test_optin_does_not_unlock_non_web_schemes(url):
    """The opt-in is about *destinations*, never about what a URL may be."""
    assert navigation_error(url, env={LOCAL_NAVIGATION_ENV: "1"}) is not None


def test_optin_reads_process_env_when_no_mapping_given(monkeypatch):
    monkeypatch.setenv(LOCAL_NAVIGATION_ENV, "1")
    assert local_navigation_allowed() is True
    assert navigation_error("http://127.0.0.1/") is None
    monkeypatch.setenv(LOCAL_NAVIGATION_ENV, "0")
    assert local_navigation_allowed() is False
    assert navigation_error("http://127.0.0.1/") is not None


# --------------------------------------------------------------------------
# DNS-backed rejection
# --------------------------------------------------------------------------

def test_hostname_resolving_to_loopback_is_rejected(monkeypatch):
    def fake_getaddrinfo(host, *_a, **_k):
        assert host == "localtest.me"
        return [(2, 1, 6, "", ("127.0.0.1", 0))]

    monkeypatch.setattr("arena.browser.navigation_policy.socket.getaddrinfo", fake_getaddrinfo)
    assert navigation_error("http://localtest.me/") == ERROR_RESOLVED_PRIVATE


def test_hostname_resolving_to_public_address_is_allowed(monkeypatch):
    monkeypatch.setattr(
        "arena.browser.navigation_policy.socket.getaddrinfo",
        lambda *_a, **_k: [(2, 1, 6, "", ("93.184.216.34", 0))],
    )
    assert navigation_error("http://example.com/") is None


def test_resolver_failure_does_not_block_navigation(monkeypatch):
    """An offline host must not lose the ability to navigate anywhere."""
    import socket as _socket

    def boom(*_a, **_k):
        raise _socket.gaierror("offline")

    monkeypatch.setattr("arena.browser.navigation_policy.socket.getaddrinfo", boom)
    assert navigation_error("http://example.com/") is None


def test_resolution_is_skipped_for_ip_literals(monkeypatch):
    def boom(*_a, **_k):
        raise AssertionError("must not resolve an address literal")

    monkeypatch.setattr("arena.browser.navigation_policy.socket.getaddrinfo", boom)
    assert navigation_error("https://93.184.216.34/") is None
    assert navigation_error("http://127.0.0.1/") == ERROR_PRIVATE


def test_mixed_dns_answer_with_one_private_address_is_rejected(monkeypatch):
    monkeypatch.setattr(
        "arena.browser.navigation_policy.socket.getaddrinfo",
        lambda *_a, **_k: [
            (2, 1, 6, "", ("93.184.216.34", 0)),
            (2, 1, 6, "", ("127.0.0.1", 0)),
        ],
    )
    assert navigation_error("http://split-horizon.example/") == ERROR_RESOLVED_PRIVATE


def test_unparseable_dns_answer_does_not_stop_the_scan(monkeypatch):
    """A junk entry must be skipped, not end the loop before the private one."""
    monkeypatch.setattr(
        "arena.browser.navigation_policy.socket.getaddrinfo",
        lambda *_a, **_k: [
            (2, 1, 6, "", ("not-an-ip", 0)),
            (2, 1, 6, "", ("127.0.0.1", 0)),
        ],
    )
    assert navigation_error("http://weird.example/") == ERROR_RESOLVED_PRIVATE


def test_empty_dns_answer_is_allowed(monkeypatch):
    monkeypatch.setattr(
        "arena.browser.navigation_policy.socket.getaddrinfo", lambda *_a, **_k: []
    )
    assert navigation_error("http://example.com/") is None


def test_unicode_error_from_resolver_is_survivable(monkeypatch):
    def boom(*_a, **_k):
        raise UnicodeError("idna")

    monkeypatch.setattr("arena.browser.navigation_policy.socket.getaddrinfo", boom)
    assert navigation_error("http://example.com/") is None


def test_optin_skips_dns_resolution_entirely(monkeypatch):
    def boom(*_a, **_k):
        raise AssertionError("opt-in must short-circuit before resolving")

    monkeypatch.setattr("arena.browser.navigation_policy.socket.getaddrinfo", boom)
    assert navigation_error("http://localtest.me/", env={LOCAL_NAVIGATION_ENV: "1"}) is None


# --------------------------------------------------------------------------
# The chokepoint: CDPBrowserPageMixin.navigate
# --------------------------------------------------------------------------

class _FakeBrowser:
    """Concrete host for the page mixin, recording what reached CDP."""

    timeout = 5

    def __init__(self):
        self.sent = []

    async def send(self, method, params=None, timeout=None):
        self.sent.append((method, params))
        return {"result": {}}

    async def wait_for_event(self, *_a, **_k):
        return {}


def _page_browser():
    from arena.browser.cdp_client.browser_page import CDPBrowserPageMixin

    class _Page(CDPBrowserPageMixin, _FakeBrowser):
        def __init__(self):
            _FakeBrowser.__init__(self)

    return _Page()


@pytest.mark.parametrize("url", BLOCKED_URLS)
def test_navigate_refuses_blocked_urls_before_touching_cdp(url):
    page = _page_browser()
    with pytest.raises(NavigationRejected):
        asyncio.run(page.navigate(url, wait=False))
    assert page.sent == [], "a rejected URL must never reach Page.navigate"


def test_navigate_allows_public_url():
    page = _page_browser()
    asyncio.run(page.navigate("https://example.com/", wait=False))
    assert page.sent == [("Page.navigate", {"url": "https://example.com/"})]


def test_navigate_allows_about_blank():
    page = _page_browser()
    asyncio.run(page.navigate(BLANK_URL, wait=False))
    assert page.sent == [("Page.navigate", {"url": BLANK_URL})]


def test_navigate_rejection_is_a_valueerror():
    """The CDP call sites funnel exceptions into responses; stay catchable."""
    assert issubclass(NavigationRejected, ValueError)


def test_navigate_guard_applies_on_the_wait_path_too():
    page = _page_browser()
    with pytest.raises(NavigationRejected):
        asyncio.run(page.navigate("file:///etc/passwd", wait=True))
    assert page.sent == []


# --------------------------------------------------------------------------
# Parity across agent-facing entry points
# --------------------------------------------------------------------------

def _cdp_navigate_handler(recorder):
    from arena.browser.cdp.page_nav import make_cdp_navigate_handler

    async def _active_tab(_tab_id=None):
        raise AssertionError("must refuse before claiming a tab")

    recorder.cdp_state = {}
    recorder.cdp_active_tab = _active_tab
    handler = make_cdp_navigate_handler(recorder)
    return getattr(handler, "__wrapped__", handler)


@pytest.mark.parametrize("url", BLOCKED_URLS)
def test_cdp_navigate_endpoint_refuses(url):
    rec = _Recorder()
    handler = _cdp_navigate_handler(rec)
    result = asyncio.run(handler(_Request({"url": url})))
    assert result["status"] == 400
    assert result["payload"]["ok"] is False
    assert rec.errors == 1
    assert rec.warnings, "a refusal should be visible in the log"


def test_cdp_navigate_endpoint_does_not_stamp_navigation_time():
    """Refusal happens before the state mutation the watcher keys off."""
    rec = _Recorder()
    handler = _cdp_navigate_handler(rec)
    asyncio.run(handler(_Request({"url": "file:///etc/passwd"})))
    assert "last_navigation_time" not in rec.cdp_state


def test_cdp_navigate_endpoint_reports_missing_url_distinctly():
    rec = _Recorder()
    handler = _cdp_navigate_handler(rec)
    result = asyncio.run(handler(_Request({})))
    assert result["status"] == 400
    assert result["payload"]["error"] == ERROR_EMPTY


def _tabs_new_handler(recorder, opened):
    from arena.browser.cdp.tabs import make_cdp_tabs_handlers

    class _Tab:
        target_id = "t1"

        def to_dict(self):
            return {"id": self.target_id}

    class _Manager:
        async def new_tab(self, url, activate=True):
            opened.append(url)
            return _Tab()

    recorder.cdp_state = {"connected": True, "manager": _Manager()}
    handlers = make_cdp_tabs_handlers(recorder)
    handler = handlers.new
    return getattr(handler, "__wrapped__", handler)


@pytest.mark.parametrize("url", BLOCKED_URLS)
def test_tabs_new_endpoint_refuses(url):
    rec = _Recorder()
    opened = []
    handler = _tabs_new_handler(rec, opened)
    result = asyncio.run(handler(_Request({"url": url})))
    assert result["status"] == 400
    assert opened == [], "a rejected URL must not open a tab"


def test_tabs_new_endpoint_still_opens_blank_tabs():
    rec = _Recorder()
    opened = []
    handler = _tabs_new_handler(rec, opened)
    result = asyncio.run(handler(_Request({})))
    assert result["status"] == 200
    assert opened == [BLANK_URL]


def _browse_handler(recorder, calls):
    from arena.browser import browse_handlers as module

    async def _fake_cdp(_ctx, **kwargs):
        calls.append(("cdp", kwargs["action"], kwargs["url"]))
        return {"payload": {"ok": True}, "status": 200}

    async def _fake_stealth(_ctx, **kwargs):
        calls.append(("stealth", kwargs["action"], kwargs["url"]))
        return {"payload": {"ok": True}, "status": 200}

    module.run_cdp_browse = _fake_cdp
    module.run_browseract_browse = _fake_stealth
    handlers = module.make_browser_browse_handlers(recorder)
    return getattr(handlers.browse, "__wrapped__", handlers.browse)


@pytest.mark.parametrize("url", BLOCKED_URLS)
@pytest.mark.parametrize("action", ["extract", "shot"])
def test_browse_endpoint_refuses_navigating_actions(url, action):
    rec = _Recorder()
    calls = []
    handler = _browse_handler(rec, calls)
    result = asyncio.run(handler(_Request({"url": url, "action": action})))
    assert result["status"] == 400
    assert calls == []


@pytest.mark.parametrize("url", BLOCKED_URLS)
def test_browse_endpoint_refuses_stealth_backend_too(url):
    """The stealth path shells out to browseract, bypassing the CDP guard."""
    rec = _Recorder()
    calls = []
    handler = _browse_handler(rec, calls)
    result = asyncio.run(handler(_Request({"url": url, "action": "extract", "stealth": True})))
    assert result["status"] == 400
    assert calls == []


@pytest.mark.parametrize("action", ["click", "type"])
def test_browse_endpoint_ignores_url_for_non_navigating_actions(action):
    """`click`/`type` act on the open tab; refusing on `url` would be wrong."""
    rec = _Recorder()
    calls = []
    handler = _browse_handler(rec, calls)
    result = asyncio.run(handler(_Request({"url": "file:///etc/passwd", "action": action})))
    assert result["status"] == 200
    assert calls == [("cdp", action, "file:///etc/passwd")]


def test_browse_endpoint_allows_public_url():
    rec = _Recorder()
    calls = []
    handler = _browse_handler(rec, calls)
    result = asyncio.run(handler(_Request({"url": "https://example.com/"})))
    assert result["status"] == 200
    assert calls == [("cdp", "extract", "https://example.com/")]


def _stealth_handler(factory_name, module_name, recorder):
    import importlib

    module = importlib.import_module(module_name)
    handler = getattr(module, factory_name)(recorder)
    return getattr(handler, "__wrapped__", handler)


@pytest.mark.parametrize("url", BLOCKED_URLS)
@pytest.mark.parametrize("factory,module_name", [
    ("make_cdp_stealth_extract_handler", "arena.browser.cdp.advanced_stealth_extract"),
    ("make_cdp_stealth_shot_handler", "arena.browser.cdp.advanced_stealth_shot"),
])
def test_stealth_endpoints_refuse(url, factory, module_name):
    rec = _Recorder()
    rec.cdp_state = {"connected": True, "manager": None}
    handler = _stealth_handler(factory, module_name, rec)
    result = asyncio.run(handler(_Request({"url": url})))
    assert result["status"] == 400


@pytest.mark.parametrize("url", BLOCKED_URLS)
def test_mcp_browser_shot_refuses(url, tmp_path):
    from arena.mcp import tool_browser

    class _Ctx:
        bin_dir = str(tmp_path)
        reports_dir = tmp_path

    def _must_not_run(*_a, **_k):
        raise AssertionError("chrome must not be launched for a rejected URL")

    result = tool_browser.handle_browser_tool(
        "browser.shot", {"url": url}, ctx=_Ctx(), run_local=_must_not_run, run_sd=_must_not_run
    )
    payload = json.loads(result["content"][0]["text"])
    assert payload["ok"] is False


def test_mcp_browser_shot_rejects_blank(tmp_path):
    from arena.mcp import tool_browser

    class _Ctx:
        bin_dir = str(tmp_path)
        reports_dir = tmp_path

    def _must_not_run(*_a, **_k):
        raise AssertionError("chrome must not be launched")

    result = tool_browser.handle_browser_tool(
        "browser.shot", {"url": BLANK_URL}, ctx=_Ctx(), run_local=_must_not_run, run_sd=_must_not_run
    )
    assert json.loads(result["content"][0]["text"])["ok"] is False


@pytest.mark.parametrize("url", BLOCKED_URLS)
def test_mcp_browser_launch_refuses(url, monkeypatch):
    from arena.mcp import tool_browser_headed

    monkeypatch.setattr(tool_browser_headed, "_prune_dead_sessions", lambda: {})
    monkeypatch.setattr(
        tool_browser_headed, "_find_chrome",
        lambda: (_ for _ in ()).throw(AssertionError("must refuse before locating chrome")),
    )
    result = tool_browser_headed._launch({"url": url})
    assert result["ok"] is False


# --------------------------------------------------------------------------
# The parity claim itself
# --------------------------------------------------------------------------

def test_every_navigating_entry_point_imports_the_policy():
    """Guards the enumeration, so a new bypass is a failing test.

    Grep-based on purpose: the defect in #103 was a call site nobody had
    listed, and only a check over the files can notice the seventh one.
    """
    root = Path(__file__).resolve().parents[1]
    required = [
        "arena/browser/cdp/page_nav.py",
        "arena/browser/cdp/tabs.py",
        "arena/browser/cdp/advanced_stealth_extract.py",
        "arena/browser/cdp/advanced_stealth_shot.py",
        "arena/browser/browse_handlers.py",
        "arena/browser/cdp_client/browser_page.py",
        "arena/mcp/tool_browser.py",
        "arena/mcp/tool_browser_headed.py",
    ]
    missing = [
        path for path in required
        if "navigation_policy" not in (root / path).read_text(encoding="utf-8")
    ]
    assert missing == [], f"navigation policy not applied in: {missing}"


def test_no_new_navigate_call_sites_bypass_the_mixin():
    """`Page.navigate` may only be issued from the guarded methods."""
    root = Path(__file__).resolve().parents[1]
    allowed = {
        "arena/browser/cdp_client/browser_page.py",  # the guarded chokepoint
        "arena/browser/cdp_client/sync_browser.py",  # local CLI, not agent-facing
    }
    offenders = []
    for path in sorted(root.joinpath("arena").rglob("*.py")):
        rel = path.relative_to(root).as_posix()
        if rel in allowed:
            continue
        text = path.read_text(encoding="utf-8")
        for line in text.splitlines():
            stripped = line.strip()
            if stripped.startswith("#") or "e.g." in stripped:
                continue  # prose, not a call
            if '"Page.navigate"' in line or "'Page.navigate'" in line:
                offenders.append(f"{rel}: {line.strip()}")
    assert offenders == [], f"Page.navigate issued outside the guard: {offenders}"
