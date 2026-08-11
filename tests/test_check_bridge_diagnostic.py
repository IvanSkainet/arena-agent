"""v4.169.39 -- tests for scripts/check_bridge.py diagnostic tool.

Verifies:
* `_read_token` precedence (explicit path, token.txt, env var);
* `probe_bridge` offline bridge error handling;
* `probe_bridge` auth validation and tool count extraction;
* `probe_bridge` 401 Unauthorized detection;
* `probe_bridge` public tunnel probing;
* `print_summary` output formatting.
"""
from __future__ import annotations

import json
import sys
import urllib.error
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import scripts.check_bridge as cb  # noqa: E402


class _FakeResponse:
    def __init__(self, data: Any):
        self._raw = json.dumps(data).encode("utf-8") if isinstance(data, dict) else data

    def read(self) -> bytes:
        return self._raw

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass


# --------------------------------------------------------------------
# 1. _read_token
# --------------------------------------------------------------------
def test_read_token_explicit_file(tmp_path):
    tok_file = tmp_path / "custom_token.txt"
    tok_file.write_text("my-secret-token\n", encoding="utf-8")
    assert cb._read_token(tok_file) == "my-secret-token"


def test_read_token_env_fallback(monkeypatch):
    monkeypatch.setenv("ARENA_BRIDGE_TOKEN", "env-secret-token")
    assert cb._read_token(Path("/nonexistent/token.txt")) == "env-secret-token"


# --------------------------------------------------------------------
# 2. probe_bridge offline
# --------------------------------------------------------------------
def test_probe_bridge_offline(monkeypatch):
    def _fail_open(*a, **k):
        raise ConnectionRefusedError("connection refused")

    monkeypatch.setattr(cb.urllib.request, "urlopen", _fail_open)
    report = cb.probe_bridge(port=8765, token="tok")
    assert report["ok"] is False
    assert report["local_online"] is False
    assert any("not responding" in err for err in report["errors"])


# --------------------------------------------------------------------
# 3. probe_bridge online & authenticated
# --------------------------------------------------------------------
def test_probe_bridge_online_happy_path(monkeypatch):
    responses = {
        "/v1/version": {"ok": True, "version": "4.169.39"},
        "/v1/self": {"ok": True, "tool_count": 240, "host": {"class": "windows"}},
        "/v1/access": {
            "ok": True,
            "tunnel_urls": ["https://pc.tail328f18.ts.net"],
            "reachable_remotely": True,
        },
        "/v1/tunnels/status": {
            "ok": True,
            "providers": {
                "tailscale": {
                    "active": True,
                    "public_url": "https://pc.tail328f18.ts.net",
                }
            },
        },
    }

    def _fake_urlopen(req, context=None, timeout=None):
        url = req.full_url if hasattr(req, "full_url") else str(req)
        for path_key, data in responses.items():
            if path_key in url:
                return _FakeResponse(data)
        # Probe of the public URL (/v1/version)
        if "https://pc.tail328f18.ts.net" in url:
            return _FakeResponse({"ok": True, "version": "4.169.39"})
        raise urllib.error.HTTPError(url, 404, "Not Found", {}, None)

    monkeypatch.setattr(cb.urllib.request, "urlopen", _fake_urlopen)

    report = cb.probe_bridge(port=8765, token="valid_tok")
    assert report["ok"] is True
    assert report["local_online"] is True
    assert report["auth_ok"] is True
    assert report["version"] == "4.169.39"
    assert report["tools_count"] == 240
    assert report["public_url"] == "https://pc.tail328f18.ts.net"
    assert report["public_reachable"] is True


def test_probe_bridge_auth_failure_401(monkeypatch):
    def _fake_urlopen(req, context=None, timeout=None):
        url = req.full_url if hasattr(req, "full_url") else str(req)
        if "/v1/version" in url:
            return _FakeResponse({"ok": True, "version": "4.169.39"})
        if "/v1/self" in url:
            raise urllib.error.HTTPError(url, 401, "Unauthorized", {}, None)
        raise urllib.error.HTTPError(url, 404, "Not Found", {}, None)

    monkeypatch.setattr(cb.urllib.request, "urlopen", _fake_urlopen)

    report = cb.probe_bridge(port=8765, token="bad_token_123")
    assert report["local_online"] is True
    assert report["auth_ok"] is False
    assert any("401 Unauthorized" in err for err in report["errors"])


def test_print_summary_formatting(capsys):
    mock_report = {
        "ok": True,
        "local_online": True,
        "auth_ok": True,
        "version": "4.169.39",
        "tools_count": 240,
        "tunnels": {
            "tailscale": {"active": True, "public_url": "https://pc.tailnet.ts.net"},
        },
        "public_url": "https://pc.tailnet.ts.net",
        "public_reachable": True,
        "errors": [],
    }
    cb.print_summary(mock_report, token="my_tok_123")
    out = capsys.readouterr().out
    assert "Bridge Status:      ONLINE (v4.169.39)" in out
    assert "https://pc.tailnet.ts.net [REACHABLE]" in out
    assert "Token: my_tok_123" in out
    assert "URL:   https://pc.tailnet.ts.net" in out
