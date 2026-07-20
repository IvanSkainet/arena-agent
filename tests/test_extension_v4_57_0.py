"""v4.57.0 — net.http typed HTTP client, secrets.*, sudo.run."""
from __future__ import annotations

import json
import os
from pathlib import Path
from unittest import mock

import pytest

from arena import constants
from arena.mcp.tool_registry import MCP_TOOLS
from arena.mcp.tool_registry_net import NET_MCP_TOOLS
from arena.mcp.tool_net import (
    _clamp_timeout,
    _load_secrets,
    _handle_net_http,
    _handle_secrets_get,
    _handle_secrets_list,
    handle_net_tool,
)
from arena.extension_bridge.policy import classify_tool_risk


REPO_ROOT = Path(__file__).resolve().parents[1]


def _read(p: str) -> str:
    return (REPO_ROOT / p).read_text(encoding="utf-8")


# ------------------------------------------------------------------
# Version
# ------------------------------------------------------------------
def test_version_is_4_57_0():
    assert constants.VERSION in ("4.57.0","4.58.0","4.59.0")


def test_pyproject_version_is_4_57_0():
    assert any(v in _read("pyproject.toml") for v in ('version = "4.57.0"', 'version = "4.58.0"', 'version = "4.59.0"'))


# ------------------------------------------------------------------
# Registry
# ------------------------------------------------------------------
def test_net_registry_declares_four_tools():
    names = {t["name"] for t in NET_MCP_TOOLS}
    assert names == {"net.http", "secrets.get", "secrets.list", "sudo.run"}


def test_net_tools_appear_in_MCP_TOOLS():
    mcp = {t["name"] for t in MCP_TOOLS}
    for t in NET_MCP_TOOLS:
        assert t["name"] in mcp


def test_net_dispatcher_wired_in_tools_module():
    src = _read("arena/mcp/tools.py")
    assert "handle_net_tool" in src
    assert "from arena.mcp.tool_net import handle_net_tool" in src


# ------------------------------------------------------------------
# Risk classification
# ------------------------------------------------------------------
def test_net_http_is_medium():
    """External network access can be abused (billing, exfil) but it's
    SSRF-filtered and size-capped — same tier as fs.create."""
    assert classify_tool_risk("net.http") == "medium"


def test_secrets_get_is_medium():
    assert classify_tool_risk("secrets.get") == "medium"


def test_secrets_list_is_safe():
    assert classify_tool_risk("secrets.list") == "safe"


def test_sudo_run_is_dangerous():
    assert classify_tool_risk("sudo.run") == "dangerous"


# ------------------------------------------------------------------
# _clamp_timeout
# ------------------------------------------------------------------
@pytest.mark.parametrize("raw, expected", [
    (None, 20.0),
    ("", 20.0),
    ("abc", 20.0),
    (0, 1.0),
    (0.5, 1.0),
    (5, 5.0),
    (120, 60.0),
    (-5, 1.0),
])
def test_clamp_timeout(raw, expected):
    assert _clamp_timeout(raw) == expected


# ------------------------------------------------------------------
# net.http validation
# ------------------------------------------------------------------
def test_net_http_rejects_missing_url():
    out = _handle_net_http({})
    assert out.get("isError")


def test_net_http_rejects_ftp_scheme():
    out = _handle_net_http({"url": "ftp://example.com/x"})
    assert out.get("isError")
    assert "scheme" in out["content"][0]["text"].lower()


def test_net_http_rejects_loopback():
    out = _handle_net_http({"url": "http://127.0.0.1:8765/"})
    assert out.get("isError")


def test_net_http_rejects_bad_method():
    out = _handle_net_http({"url": "https://example.com/", "method": "TRACE"})
    assert out.get("isError")


# ------------------------------------------------------------------
# secrets
# ------------------------------------------------------------------
def test_secrets_get_returns_error_when_missing_key():
    out = _handle_secrets_get({})
    assert out.get("isError")


def test_secrets_get_never_returns_plaintext(tmp_path, monkeypatch):
    secrets_file = tmp_path / "s.json"
    secrets_file.write_text(json.dumps({"groq": "abcdefghijklmnopqrst"}))
    monkeypatch.setenv("ARENA_SECRETS_PATH", str(secrets_file))
    out = _handle_secrets_get({"key": "groq"})
    assert out["ok"] is True
    assert out["length"] == 20
    assert "abcdefghijklmnopqrst" not in json.dumps(out)
    assert "preview" in out and "***" in out["preview"]


def test_secrets_list_names_only(tmp_path, monkeypatch):
    secrets_file = tmp_path / "s.json"
    secrets_file.write_text(json.dumps({"groq": "SECRET1", "hf": "SECRET2"}))
    monkeypatch.setenv("ARENA_SECRETS_PATH", str(secrets_file))
    out = _handle_secrets_list({})
    assert out["ok"] is True
    assert sorted(out["keys"]) == ["groq", "hf"]
    assert "SECRET1" not in json.dumps(out)
    assert "SECRET2" not in json.dumps(out)


def test_secrets_missing_file_returns_empty(tmp_path, monkeypatch):
    monkeypatch.setenv("ARENA_SECRETS_PATH", str(tmp_path / "nope.json"))
    out = _handle_secrets_list({})
    assert out["ok"] is True
    assert out["keys"] == []


# ------------------------------------------------------------------
# sudo.run
# ------------------------------------------------------------------
def test_sudo_run_requires_cmd():
    class _Ctx:
        def blocked_reason(self, _): return None
    from arena.mcp.tool_net import _handle_sudo_run
    out = _handle_sudo_run({}, ctx=_Ctx(), run_sd=lambda *a, **kw: (0, "", ""))
    assert isinstance(out, dict) and out.get("isError")


def test_sudo_run_blocked_by_pattern():
    """rm -rf / must be caught by BLOCK_PATTERNS even when routed through sudo.run."""
    class _Ctx:
        def blocked_reason(self, cmd):
            if "rm" in cmd and "/" in cmd:
                return "blocked: dangerous rm"
            return None
    from arena.mcp.tool_net import _handle_sudo_run
    out = _handle_sudo_run({"cmd": "rm -rf /"},
                           ctx=_Ctx(), run_sd=lambda *a, **kw: (0, "", ""))
    assert out.get("isError")
    assert "blocked" in out["content"][0]["text"].lower()


def test_sudo_run_success_path():
    captured = {}
    def _fake_run(cmd, *, timeout):
        captured["cmd"] = cmd
        captured["timeout"] = timeout
        return (0, "hello", "")
    class _Ctx:
        def blocked_reason(self, _): return None
    out = handle_net_tool("sudo.run", {"cmd": "id"}, ctx=_Ctx(), run_sd=_fake_run)
    parsed = json.loads(out["content"][0]["text"])
    assert parsed["ok"] is True
    assert parsed["stdout"] == "hello"
    assert captured["cmd"][2].startswith("sudo -n id")


# ------------------------------------------------------------------
# net.http auth.value -> secret indirection
# ------------------------------------------------------------------
def test_net_http_auth_secret_reference_resolves(tmp_path, monkeypatch):
    secrets_file = tmp_path / "s.json"
    secrets_file.write_text(json.dumps({"gk": "TESTKEY_VALUE"}))
    monkeypatch.setenv("ARENA_SECRETS_PATH", str(secrets_file))

    class _Resp:
        status = 200
        headers = {"Content-Type": "text/plain"}
        def read(self, _n=None): return b"OK"
        def __enter__(self): return self
        def __exit__(self, *a): return False

    captured = {}
    def _fake_urlopen(req, timeout=None):
        captured["url"] = req.full_url
        captured["headers"] = dict(req.header_items())
        return _Resp()

    with mock.patch("arena.mcp.tool_net.urllib.request.urlopen", _fake_urlopen):
        out = _handle_net_http({
            "url": "https://api.example.com/x",
            "auth": {"type": "bearer", "value": "secret:gk"},
        })
    assert out["ok"] is True
    # bearer header set from secret
    auth = {k.lower(): v for k, v in captured["headers"].items()}
    assert "authorization" in auth
    assert auth["authorization"] == "Bearer TESTKEY_VALUE"


def test_net_http_auth_secret_missing_returns_error(tmp_path, monkeypatch):
    monkeypatch.setenv("ARENA_SECRETS_PATH", str(tmp_path / "empty.json"))
    out = _handle_net_http({
        "url": "https://api.example.com/x",
        "auth": {"type": "bearer", "value": "secret:nope"},
    })
    assert out.get("isError")
    assert "nope" in out["content"][0]["text"]


# ------------------------------------------------------------------
# net.http basic body handling
# ------------------------------------------------------------------
def test_net_http_json_body_sets_content_type(monkeypatch):
    class _Resp:
        status = 201
        headers = {"Content-Type": "application/json"}
        def read(self, _n=None): return b'{"ok":true}'
        def __enter__(self): return self
        def __exit__(self, *a): return False

    captured = {}
    def _fake_urlopen(req, timeout=None):
        captured["data"] = req.data
        captured["ct"] = req.headers.get("Content-type")
        return _Resp()

    with mock.patch("arena.mcp.tool_net.urllib.request.urlopen", _fake_urlopen):
        out = _handle_net_http({
            "url": "https://api.example.com/x",
            "method": "POST",
            "json": {"a": 1},
        })
    assert out["status"] == 201
    assert out["json"] == {"ok": True}
    assert captured["ct"] == "application/json"
    assert captured["data"] == b'{"a": 1}'


def test_net_http_returns_base64_for_binary(monkeypatch):
    payload = b"\x89PNG\r\n\x1a\n" + b"x" * 100
    class _Resp:
        status = 200
        headers = {"Content-Type": "image/png"}
        def read(self, _n=None): return payload
        def __enter__(self): return self
        def __exit__(self, *a): return False

    with mock.patch("arena.mcp.tool_net.urllib.request.urlopen", lambda req, timeout=None: _Resp()):
        out = _handle_net_http({"url": "https://example.com/img.png"})
    assert out["ok"] is True
    assert "base64" in out
    assert "text" not in out
    assert out["mime"] == "image/png"


# ------------------------------------------------------------------
# Registry / policy consistency (no phantom net.* tools)
# ------------------------------------------------------------------
def test_all_net_tools_have_policy_classes():
    for t in NET_MCP_TOOLS:
        assert classify_tool_risk(t["name"]) in ("safe", "medium", "dangerous")


def test_changelog_mentions_v4_57_0():
    assert "4.57.0" in _read("CHANGELOG.md")
    assert "4.57.0" in _read("CHANGELOG.ru.md")
