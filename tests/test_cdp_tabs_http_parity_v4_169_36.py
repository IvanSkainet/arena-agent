"""v4.169.36 -- arena.browser.cdp_client.tabs_http parity tests (mutation-driven).

Fast, isolated tests for CDP HTTP debug client:
* `list_tabs` url formation (http://127.0.0.1:<port>/json/list), timeout=5, JSON array decoding, exception fallback to [];
* `_loopback_ws_url` validation: schemes (ws/wss), loopback hostnames (127.0.0.1, localhost, ::1, [::1]), port matching, non-string handling;
* `get_websocket_url` tab filtering (type=="page", "webSocketDebuggerUrl" in tab), index bounds check (0 <= tab_index < len), default port/index;
* `get_new_tab_url` PUT method attempt, GET fallback on error, loopback validation, None on double failure;
* `close_tab` url formation (/json/close/<id>), "Target is closing" match vs mismatch, exception fallback to False.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from arena.browser.cdp_client import tabs_http  # noqa: E402


class _FakeResponse:
    def __init__(self, data: bytes | str):
        self._data = data.encode("utf-8") if isinstance(data, str) else data

    def read(self) -> bytes:
        return self._data

    def decode(self) -> str:
        return self._data.decode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass


# --------------------------------------------------------------------
# 0. Pinned Constants
# --------------------------------------------------------------------
def test_loopback_hosts_exact_set():
    assert tabs_http._LOOPBACK_HOSTS == frozenset({"127.0.0.1", "localhost", "::1", "[::1]"})


# --------------------------------------------------------------------
# 1. list_tabs
# --------------------------------------------------------------------
def test_list_tabs_happy_path(monkeypatch):
    captured = {}

    def _fake_urlopen(url, timeout=None):
        captured["url"] = url
        captured["timeout"] = timeout
        return _FakeResponse(json.dumps([{"id": "tab1", "type": "page"}]))

    monkeypatch.setattr(tabs_http.urllib.request, "urlopen", _fake_urlopen)
    res = tabs_http.list_tabs(9222)
    assert captured["url"] == "http://127.0.0.1:9222/json/list"
    assert captured["timeout"] == 5
    assert res == [{"id": "tab1", "type": "page"}]


def test_list_tabs_default_port(monkeypatch):
    captured = {}

    def _fake_urlopen(url, timeout=None):
        captured["url"] = url
        return _FakeResponse("[]")

    monkeypatch.setattr(tabs_http.urllib.request, "urlopen", _fake_urlopen)
    res = tabs_http.list_tabs()
    assert captured["url"] == f"http://127.0.0.1:{tabs_http.DEFAULT_PORT}/json/list"
    assert res == []


def test_list_tabs_exception_returns_empty_list(monkeypatch):
    def _raise_urlopen(url, timeout=None):
        raise ConnectionRefusedError("no browser")

    monkeypatch.setattr(tabs_http.urllib.request, "urlopen", _raise_urlopen)
    assert tabs_http.list_tabs(9222) == []


# --------------------------------------------------------------------
# 2. _loopback_ws_url
# --------------------------------------------------------------------
@pytest.mark.parametrize(
    "raw,port,expected",
    [
        ("ws://127.0.0.1:9222/devtools/page/1", 9222, "ws://127.0.0.1:9222/devtools/page/1"),
        ("wss://127.0.0.1:9222/devtools/page/1", 9222, "wss://127.0.0.1:9222/devtools/page/1"),
        ("ws://localhost:9222/devtools/page/1", 9222, "ws://localhost:9222/devtools/page/1"),
        ("ws://[::1]:9222/devtools/page/1", 9222, "ws://[::1]:9222/devtools/page/1"),
        # Rejections
        ("http://127.0.0.1:9222/page/1", 9222, None),
        ("ws://attacker.com:9222/page/1", 9222, None),
        ("ws://127.0.0.1:9999/page/1", 9222, None),
        ("ws://:9222/x", 9222, None),  # missing hostname -> parsed.hostname is None
        ("", 9222, None),
        (None, 9222, None),
        (12345, 9222, None),
        ([], 9222, None),
    ],
)
def test_loopback_ws_url_cases(raw, port, expected):
    assert tabs_http._loopback_ws_url(raw, port) == expected


def test_loopback_ws_url_each_host_isolated():
    # Individual checks to kill literal-mutation mutants
    assert tabs_http._loopback_ws_url("ws://127.0.0.1:8000/x", 8000) == "ws://127.0.0.1:8000/x"
    assert tabs_http._loopback_ws_url("ws://localhost:8000/x", 8000) == "ws://localhost:8000/x"
    assert tabs_http._loopback_ws_url("ws://[::1]:8000/x", 8000) == "ws://[::1]:8000/x"


# --------------------------------------------------------------------
# 3. get_websocket_url
# --------------------------------------------------------------------
def test_get_websocket_url_success_and_defaults(monkeypatch):
    tabs_data = [
        {"type": "background", "webSocketDebuggerUrl": "ws://127.0.0.1:9222/bg"},
        {"type": "page", "webSocketDebuggerUrl": "ws://127.0.0.1:9222/page0"},
        {"type": "page", "webSocketDebuggerUrl": "ws://127.0.0.1:9222/page1"},
    ]
    monkeypatch.setattr(tabs_http, "list_tabs", lambda port: tabs_data)

    # Call with explicit indices
    assert tabs_http.get_websocket_url(9222, 0) == "ws://127.0.0.1:9222/page0"
    assert tabs_http.get_websocket_url(9222, 1) == "ws://127.0.0.1:9222/page1"

    # Call without tab_index (tests default tab_index=0)
    assert tabs_http.get_websocket_url(9222) == "ws://127.0.0.1:9222/page0"


@pytest.mark.parametrize("invalid_idx", [-1, 2, 5])
def test_get_websocket_url_out_of_bounds(monkeypatch, invalid_idx):
    tabs_data = [
        {"type": "page", "webSocketDebuggerUrl": "ws://127.0.0.1:9222/page0"},
        {"type": "page", "webSocketDebuggerUrl": "ws://127.0.0.1:9222/page1"},
    ]
    monkeypatch.setattr(tabs_http, "list_tabs", lambda port: tabs_data)
    assert tabs_http.get_websocket_url(9222, invalid_idx) is None


def test_get_websocket_url_no_matching_page_tabs(monkeypatch):
    tabs_data = [
        {"type": "iframe", "id": "1"},
        {"type": "page"},  # missing webSocketDebuggerUrl
    ]
    monkeypatch.setattr(tabs_http, "list_tabs", lambda port: tabs_data)
    assert tabs_http.get_websocket_url(9222, 0) is None


# --------------------------------------------------------------------
# 4. get_new_tab_url
# --------------------------------------------------------------------
def test_get_new_tab_url_put_success(monkeypatch):
    captured_reqs = []
    captured_timeouts = []

    def _fake_urlopen(req, timeout=None):
        captured_reqs.append(req)
        captured_timeouts.append(timeout)
        return _FakeResponse(json.dumps({"webSocketDebuggerUrl": "ws://127.0.0.1:9222/new_tab"}))

    monkeypatch.setattr(tabs_http.urllib.request, "urlopen", _fake_urlopen)
    res = tabs_http.get_new_tab_url(9222)
    assert res == "ws://127.0.0.1:9222/new_tab"
    assert len(captured_reqs) == 1
    assert captured_reqs[0].get_method() == "PUT"
    assert captured_reqs[0].full_url == "http://127.0.0.1:9222/json/new"
    assert captured_timeouts == [5]


def test_get_new_tab_url_put_fails_get_fallback(monkeypatch):
    call_count = [0]
    captured_timeouts = []

    def _fake_urlopen(req_or_url, timeout=None):
        call_count[0] += 1
        captured_timeouts.append(timeout)
        if call_count[0] == 1:
            raise OSError("PUT not allowed (405)")
        # Second call is GET fallback
        return _FakeResponse(json.dumps({"webSocketDebuggerUrl": "ws://127.0.0.1:9222/fallback_tab"}))

    monkeypatch.setattr(tabs_http.urllib.request, "urlopen", _fake_urlopen)
    res = tabs_http.get_new_tab_url(9222)
    assert res == "ws://127.0.0.1:9222/fallback_tab"
    assert call_count[0] == 2
    assert captured_timeouts == [5, 5]


def test_get_new_tab_url_both_fail_returns_none(monkeypatch):
    def _fail_all(req_or_url, timeout=None):
        raise ConnectionError("refused")

    monkeypatch.setattr(tabs_http.urllib.request, "urlopen", _fail_all)
    assert tabs_http.get_new_tab_url(9222) is None


# --------------------------------------------------------------------
# 5. close_tab
# --------------------------------------------------------------------
def test_close_tab_success(monkeypatch):
    captured = {}

    def _fake_urlopen(url, timeout=None):
        captured["url"] = url
        captured["timeout"] = timeout
        return _FakeResponse("Target is closing\n")

    monkeypatch.setattr(tabs_http.urllib.request, "urlopen", _fake_urlopen)
    ok = tabs_http.close_tab("TAB_123", 9222)
    assert ok is True
    assert captured["url"] == "http://127.0.0.1:9222/json/close/TAB_123"
    assert captured["timeout"] == 5


def test_close_tab_unexpected_response(monkeypatch):
    def _fake_urlopen(url, timeout=None):
        return _FakeResponse("Target not found")

    monkeypatch.setattr(tabs_http.urllib.request, "urlopen", _fake_urlopen)
    assert tabs_http.close_tab("TAB_999", 9222) is False


def test_close_tab_exception_returns_false(monkeypatch):
    def _fail(url, timeout=None):
        raise OSError("network error")

    monkeypatch.setattr(tabs_http.urllib.request, "urlopen", _fail)
    assert tabs_http.close_tab("TAB_123", 9222) is False
