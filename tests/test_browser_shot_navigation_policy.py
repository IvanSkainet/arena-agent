"""`browser.shot` is a navigation too (#103 follow-up).

Both MCP screenshot tools hand the agent's URL to a headless Chromium on its
command line. That reaches loopback, link-local metadata and `file://`
exactly like `Page.navigate` does -- it simply never travels over CDP, so the
CDP-shaped guard did not see it. These tests drive the real handlers and
assert on the strongest available signal: no browser process was launched.
"""
from __future__ import annotations

import json
import socket
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

# See tests/test_cdp_navigation_policy.py: the suite has no conftest putting
# the repository root on sys.path, so the imports below are E402 by design.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from arena.mcp.tool_browser import handle_browser_tool  # noqa: E402

HOSTILE_URLS = [
    "http://127.0.0.1:8765/v1/status",
    "http://localhost:9222/json/version",
    "http://169.254.169.254/latest/meta-data/",
    "http://192.168.1.1/admin",
    "http://[::1]:8765/",
    "http://2130706433:8765/v1/status",
    "file:///etc/passwd",
    "file:///C:/Windows/win.ini",
    "http://metadata.google.internal/computeMetadata/v1/",
]


@pytest.fixture(autouse=True)
def _no_real_dns(monkeypatch):
    """Deterministic public answer; literal IPs never reach the resolver."""
    def fake_getaddrinfo(host, *args, **kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 0))]

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)


@pytest.fixture(autouse=True)
def _no_local_opt_in(monkeypatch):
    monkeypatch.delenv("ARENA_BROWSER_ALLOW_LOCAL_NAV", raising=False)


class _Spy:
    """Stands in for run_sd and records whether a browser was launched."""

    def __init__(self):
        self.commands = []

    def __call__(self, cmd, timeout=None):
        self.commands.append(cmd)
        return 0, "", ""


def _ctx(tmp_path):
    return SimpleNamespace(bin_dir=str(tmp_path), reports_dir=tmp_path)


def _payload(result):
    return json.loads(result["content"][0]["text"])


@pytest.mark.parametrize("url", HOSTILE_URLS)
def test_browser_shot_refuses_without_launching_a_browser(url, tmp_path):
    spy = _Spy()
    result = handle_browser_tool(
        "browser.shot", {"url": url}, ctx=_ctx(tmp_path), run_local=_Spy(), run_sd=spy,
    )
    body = _payload(result)
    assert body["ok"] is False, f"{url} was not refused"
    assert body["error"]
    assert spy.commands == [], f"a browser was launched for {url}: {spy.commands}"


def test_browser_shot_still_takes_a_screenshot_of_a_public_url(tmp_path):
    """Positive control: refusing everything would pass the test above."""
    spy = _Spy()
    result = handle_browser_tool(
        "browser.shot", {"url": "https://example.com/"},
        ctx=_ctx(tmp_path), run_local=_Spy(), run_sd=spy,
    )
    body = _payload(result)
    assert body["ok"] is True
    assert body["url"] == "https://example.com/"
    assert len(spy.commands) == 1
    assert "https://example.com/" in spy.commands[0]


def test_browser_shot_screenshots_the_validated_url_not_the_raw_input(tmp_path):
    """The policy's return value must be what reaches the command line.

    Dropping the result and passing `args["url"]` through would keep every
    refusal test green while handing Chromium the unnormalised string.
    """
    spy = _Spy()
    handle_browser_tool(
        "browser.shot", {"url": "  https://example.com/x  "},
        ctx=_ctx(tmp_path), run_local=_Spy(), run_sd=spy,
    )
    assert "https://example.com/x" in spy.commands[0]
    assert "  https://example.com/x  " not in spy.commands[0]


def test_browser_shot_requires_a_url(tmp_path):
    spy = _Spy()
    body = _payload(handle_browser_tool(
        "browser.shot", {}, ctx=_ctx(tmp_path), run_local=_Spy(), run_sd=spy,
    ))
    assert body["ok"] is False
    assert "url" in body["error"]
    assert spy.commands == []
