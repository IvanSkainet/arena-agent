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
import urllib.parse
from pathlib import Path
from typing import Any

import pytest

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
        "/v1/version": {"ok": True, "version": "4.169.38"},
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
        parsed = urllib.parse.urlparse(url)
        if parsed.hostname == "pc.tail328f18.ts.net":
            return _FakeResponse({"ok": True, "version": "4.169.38"})
        for path_key, data in responses.items():
            if url.endswith(path_key):
                return _FakeResponse(data)
        raise urllib.error.HTTPError(url, 404, "Not Found", {}, None)

    monkeypatch.setattr(cb.urllib.request, "urlopen", _fake_urlopen)

    report = cb.probe_bridge(port=8765, token="valid_tok")
    assert report["ok"] is True
    assert report["local_online"] is True
    assert report["auth_ok"] is True
    assert report["version"] == "4.169.38"
    assert report["tools_count"] == 240
    assert report["public_url"] == "https://pc.tail328f18.ts.net"
    assert report["public_reachable"] is True


def test_probe_bridge_auth_failure_401(monkeypatch):
    def _fake_urlopen(req, context=None, timeout=None):
        url = req.full_url if hasattr(req, "full_url") else str(req)
        if url.endswith("/v1/version"):
            return _FakeResponse({"ok": True, "version": "4.169.38"})
        if url.endswith("/v1/self"):
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
        "version": "4.169.38",
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
    assert "Bridge Status:      ONLINE (v4.169.38)" in out
    assert "https://pc.tailnet.ts.net [REACHABLE]" in out
    assert "Token: my_tok_123" in out
    assert "URL:   https://pc.tailnet.ts.net" in out


# ---------------------------------------------------------------------------
# public_url validation (#245)
#
# `public_url` is echoed back by the bridge, not supplied by the operator,
# so a compromised or misconfigured bridge picks where this diagnostic
# connects. Demonstrated before the fix with a fake bridge reporting
# `file:///etc/hostname`: the tool opened `file:///etc/hostname/v1/version`.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("hostile", [
    "file:///etc/hostname",
    "file:///etc/passwd",
    "ftp://attacker.example/x",
    "gopher://attacker.example/",
    "data:text/plain,hello",
    "http:///v1/version",          # no host at all
    "://no-scheme.example",
    "",
    "   ",
])
def test_hostile_public_url_is_refused(hostile):
    assert cb.safe_probe_url(hostile) is None, (
        f"{hostile!r} must not be fetched: only http/https with a host"
    )


@pytest.mark.parametrize("legit", [
    "https://tunnel.trycloudflare.com",
    "https://abc123.ngrok-free.app/",
    "http://bore.pub:12345",
    "https://host.tail328f18.ts.net",
])
def test_legitimate_tunnel_urls_still_probe(legit):
    """The fix must not break the diagnostic it protects.

    Every supported provider shape has to survive, which is why this
    validates scheme+host rather than allowlisting domains: a stale
    domain list would silently reject a working tunnel.
    """
    assert cb.safe_probe_url(legit) == legit.rstrip("/")


def test_non_string_public_url_is_refused():
    """A bridge returning JSON null or a number must not crash the probe."""
    for value in (None, 123, {"url": "x"}, ["https://x"]):
        assert cb.safe_probe_url(value) is None


def test_probe_refuses_a_hostile_public_url_end_to_end(monkeypatch):
    """The validator must be wired in, not merely present.

    A helper nobody calls fixes nothing. This drives probe_bridge with a
    bridge that authenticates and then reports a `file:` URL, and asserts
    no non-HTTP fetch is attempted and the operator is told why.
    """
    opened: list[str] = []

    class _Resp:
        def __init__(self, payload):
            self._payload = json.dumps(payload).encode()

        def read(self):
            return self._payload

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def fake_urlopen(req, *a, **k):
        url = req.full_url if hasattr(req, "full_url") else str(req)
        opened.append(url)
        if url.endswith("/v1/version"):
            return _Resp({"version": "9.9.9"})
        if url.endswith("/v1/self"):
            return _Resp({"ok": True, "tool_count": 7})
        if url.endswith("/v1/access"):
            return _Resp({"tunnel_urls": ["file:///etc/hostname"]})
        if url.endswith("/v1/tunnels/status"):
            return _Resp({"providers": {"evil": {
                "active": True, "public_url": "file:///etc/hostname"}}})
        return _Resp({})

    monkeypatch.setattr(cb.urllib.request, "urlopen", fake_urlopen)
    report = cb.probe_bridge(port=8798, token="x", timeout=1)

    non_http = [u for u in opened if not u.startswith(("http://", "https://"))]
    assert not non_http, f"a non-HTTP URL was fetched: {non_http}"
    assert any("refusing to probe public_url" in e for e in report["errors"]), (
        "the operator must be told the URL was rejected, not left to wonder "
        "why the probe silently did nothing"
    )
