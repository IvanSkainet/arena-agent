"""v4.60.12: scripts/check_latest_release.py

Previous install.bat used ``python -c "import urllib.request,json; ..."``
with no User-Agent and no token support. GitHub anonymous rate limit
(60/h shared IP) turned that into ``[INFO] Could not check GitHub for
newer releases - offline or rate-limited`` after ~5 install runs from
the same box in an hour (Ivan's actual field failure).

The replacement helper:
  1. HEADs the ``/releases/latest`` redirect (not rate-limited).
  2. Falls back to the JSON API with User-Agent + optional GITHUB_TOKEN.
  3. Prints a precise hint to stderr rather than the generic ``offline``.

These tests exercise the helper in isolation (no real network) by
monkeypatching ``urllib.request.urlopen``.
"""
from __future__ import annotations

import importlib.util
import io
from pathlib import Path
from urllib.error import HTTPError, URLError

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
CHECK_SCRIPT = REPO_ROOT / "scripts" / "check_latest_release.py"


def _load_check_module():
    spec = importlib.util.spec_from_file_location("_check_release_mod", CHECK_SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class _FakeResponse:
    def __init__(self, url: str, body: bytes = b""):
        self._url = url
        self._body = body

    def geturl(self) -> str:
        return self._url

    def read(self) -> bytes:
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_redirect_path_returns_tag_without_v_prefix(monkeypatch):
    mod = _load_check_module()
    def fake_urlopen(req, timeout=None):
        # HEAD request to /releases/latest — return a fake 302 target
        return _FakeResponse("https://github.com/x/y/releases/tag/v4.60.11")
    monkeypatch.setattr(mod.urllib.request, "urlopen", fake_urlopen)
    assert mod._fetch_via_redirect("x/y") == "4.60.11"


def test_redirect_path_handles_non_v_prefix(monkeypatch):
    """Older tags without the ``v`` prefix must still work."""
    mod = _load_check_module()
    def fake_urlopen(req, timeout=None):
        return _FakeResponse("https://github.com/x/y/releases/tag/1.2.3")
    monkeypatch.setattr(mod.urllib.request, "urlopen", fake_urlopen)
    assert mod._fetch_via_redirect("x/y") == "1.2.3"


def test_redirect_path_returns_none_on_url_error(monkeypatch):
    mod = _load_check_module()
    def fake_urlopen(req, timeout=None):
        raise URLError("nowhere")
    monkeypatch.setattr(mod.urllib.request, "urlopen", fake_urlopen)
    assert mod._fetch_via_redirect("x/y") is None


def test_api_path_returns_rate_limit_hint_on_403(monkeypatch):
    mod = _load_check_module()
    def fake_urlopen(req, timeout=None):
        raise HTTPError("https://api.github.com/x", 403, "rate limit", {}, None)
    monkeypatch.setattr(mod.urllib.request, "urlopen", fake_urlopen)
    tag, hint = mod._fetch_via_api("x/y", token=None)
    assert tag is None
    assert hint and "rate limit" in hint.lower()
    assert "GITHUB_TOKEN" in hint or "GH_TOKEN" in hint


def test_api_path_returns_rate_limit_hint_on_429(monkeypatch):
    """Secondary rate-limit surfaces as 429; treat it the same."""
    mod = _load_check_module()
    def fake_urlopen(req, timeout=None):
        raise HTTPError("https://api.github.com/x", 429, "too many", {}, None)
    monkeypatch.setattr(mod.urllib.request, "urlopen", fake_urlopen)
    tag, hint = mod._fetch_via_api("x/y", token=None)
    assert tag is None and hint and "GITHUB_TOKEN" in hint


def test_api_path_returns_tag_from_json(monkeypatch):
    mod = _load_check_module()
    def fake_urlopen(req, timeout=None):
        body = b'{"tag_name": "v4.60.12"}'
        return _FakeResponse("https://api.github.com/x", body)
    monkeypatch.setattr(mod.urllib.request, "urlopen", fake_urlopen)
    tag, hint = mod._fetch_via_api("x/y", token=None)
    assert tag == "4.60.12"
    assert hint is None


def test_api_path_sets_authorization_when_token_present(monkeypatch):
    mod = _load_check_module()
    captured: dict = {}
    def fake_urlopen(req, timeout=None):
        captured["headers"] = dict(req.header_items())
        return _FakeResponse("https://api.github.com/x", b'{"tag_name":"v9.9.9"}')
    monkeypatch.setattr(mod.urllib.request, "urlopen", fake_urlopen)
    tag, hint = mod._fetch_via_api("x/y", token="ghp_TESTTOKEN")
    assert tag == "9.9.9"
    # Header names are case-insensitive; check case-insensitively.
    lower_keys = {k.lower(): v for k, v in captured["headers"].items()}
    assert lower_keys.get("authorization") == "token ghp_TESTTOKEN"


def test_user_agent_is_always_present(monkeypatch):
    """GitHub refuses API requests without an explicit User-Agent."""
    mod = _load_check_module()
    captured: dict = {}
    def fake_urlopen(req, timeout=None):
        captured["headers"] = dict(req.header_items())
        return _FakeResponse("https://github.com/x/y/releases/tag/v1.0.0")
    monkeypatch.setattr(mod.urllib.request, "urlopen", fake_urlopen)
    mod._fetch_via_redirect("x/y")
    lower_keys = {k.lower(): v for k, v in captured["headers"].items()}
    assert "user-agent" in lower_keys
    assert "arena-agent" in lower_keys["user-agent"].lower()


def test_check_prints_tag_to_stdout_on_success(monkeypatch, capsys):
    mod = _load_check_module()
    monkeypatch.setattr(mod, "_fetch_via_redirect", lambda repo: "4.60.11")
    rc = mod.check("x/y")
    out = capsys.readouterr()
    assert rc == 0
    assert out.out.strip() == "4.60.11"


def test_check_prints_hint_to_stderr_on_failure(monkeypatch, capsys):
    mod = _load_check_module()
    monkeypatch.setattr(mod, "_fetch_via_redirect", lambda repo: None)
    monkeypatch.setattr(mod, "_fetch_via_api", lambda repo, token: (None, "GitHub API rate limit exceeded (60/h anonymous). Set GITHUB_TOKEN..."))
    rc = mod.check("x/y")
    out = capsys.readouterr()
    assert rc == 1
    assert out.out == ""
    assert "GITHUB_TOKEN" in out.err


def test_token_read_from_env(monkeypatch):
    mod = _load_check_module()
    for var in ("GITHUB_TOKEN", "GH_TOKEN", "ARENA_GITHUB_TOKEN"):
        monkeypatch.delenv(var, raising=False)
    assert mod._token_from_env() is None
    monkeypatch.setenv("GH_TOKEN", "gh_abc")
    assert mod._token_from_env() == "gh_abc"
    monkeypatch.setenv("GITHUB_TOKEN", "gh_first_wins")
    assert mod._token_from_env() == "gh_first_wins"


def test_main_accepts_owner_repo_positional(monkeypatch, capsys):
    mod = _load_check_module()
    monkeypatch.setattr(mod, "_fetch_via_redirect", lambda repo: repo + "-tag")
    rc = mod.main(["owner/repo"])
    out = capsys.readouterr()
    assert rc == 0 and out.out.strip() == "owner/repo-tag"


def test_script_import_side_effects_are_none(monkeypatch):
    """Importing the module must not fire off a real network request."""
    called = {"n": 0}
    real = _load_check_module()
    orig_urlopen = real.urllib.request.urlopen
    def counting_urlopen(*a, **kw):
        called["n"] += 1
        return orig_urlopen(*a, **kw)
    real.urllib.request.urlopen = counting_urlopen
    # Re-import fresh
    _load_check_module()
    assert called["n"] == 0
    real.urllib.request.urlopen = orig_urlopen
