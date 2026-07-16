"""Tests for the v4.39.0 persistent URL memory module.

Covers the ``arena/agentctl_cli/url_cache.py`` module in
isolation -- no bridge calls, no CLI subprocess. Integration
tests for the fallback loop itself live in
``tests/test_url_cache_fallback.py``.

Test surface:
  * save() round-trips through load()
  * cache location honours ARENA_URL_CACHE_PATH
  * ARENA_BRIDGE_URL_CACHE truthy-off shapes disable cache
  * empty urls list -> save() returns None (no empty snapshot)
  * malformed on-disk file -> load() returns None silently
  * schema version mismatch -> load() returns None silently
  * atomic write leaves no .tmp file after normal run
  * fallback_bootstrap_urls preserves order + dedupes
  * clear() is idempotent + respects disable flag
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from arena.agentctl_cli import url_cache


@pytest.fixture
def cache_dir(tmp_path, monkeypatch):
    """Redirect the cache to a per-test tmp directory so tests
    don't collide with each other or with a real user cache."""
    p = tmp_path / "last_urls.json"
    monkeypatch.setenv("ARENA_URL_CACHE_PATH", str(p))
    monkeypatch.delenv("ARENA_BRIDGE_URL_CACHE", raising=False)
    return p


# ---------------------------------------------------------------------------
# Path resolution
# ---------------------------------------------------------------------------
def test_cache_path_defaults_to_arena_home(monkeypatch):
    monkeypatch.delenv("ARENA_URL_CACHE_PATH", raising=False)
    assert url_cache.cache_path() == Path.home() / ".arena" / "last_urls.json"


def test_cache_path_respects_env_override(tmp_path, monkeypatch):
    p = tmp_path / "custom" / "urls.json"
    monkeypatch.setenv("ARENA_URL_CACHE_PATH", str(p))
    assert url_cache.cache_path() == p


# ---------------------------------------------------------------------------
# Disable flag
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("val,expected", [
    ("0", True), ("false", True), ("FALSE", True),
    ("no", True), ("NO", True), ("off", True), ("Off", True),
    ("1", False), ("true", False), ("yes", False), ("on", False),
    ("", False), ("anything else", False),
])
def test_is_disabled_shapes(monkeypatch, val, expected):
    monkeypatch.setenv("ARENA_BRIDGE_URL_CACHE", val)
    assert url_cache.is_disabled() is expected


def test_is_disabled_unset_is_enabled(monkeypatch):
    """Cache is on by default -- opting in would leave the
    'invisible failure on outage' trap in place."""
    monkeypatch.delenv("ARENA_BRIDGE_URL_CACHE", raising=False)
    assert url_cache.is_disabled() is False


# ---------------------------------------------------------------------------
# save() + load() round-trip
# ---------------------------------------------------------------------------
def test_save_writes_and_load_reads(cache_dir):
    cfg = {"urls": [
        {"provider": "tailscale", "url": "https://ts.example", "kind": "https"},
        {"provider": "ngrok", "url": "https://ng.example", "kind": "https"},
    ]}
    written = url_cache.save(cfg, bootstrap_url="https://ts.example")
    assert written == cache_dir
    assert cache_dir.exists()

    loaded = url_cache.load()
    assert loaded is not None
    assert loaded["version"] == url_cache.CACHE_VERSION
    assert loaded["bootstrap_url"] == "https://ts.example"
    assert len(loaded["urls"]) == 2
    assert loaded["urls"][0]["provider"] == "tailscale"
    assert loaded["urls"][1]["url"] == "https://ng.example"
    assert isinstance(loaded["saved_at"], int)
    assert loaded["saved_at"] > 0


def test_save_creates_parent_directory(tmp_path, monkeypatch):
    """save() must mkdir the parent when it doesn't exist yet
    (first run on a fresh ~/.arena/)."""
    nested = tmp_path / "does" / "not" / "exist" / "urls.json"
    monkeypatch.setenv("ARENA_URL_CACHE_PATH", str(nested))
    monkeypatch.delenv("ARENA_BRIDGE_URL_CACHE", raising=False)
    result = url_cache.save({"urls": [{"provider": "x", "url": "https://x"}]},
                            bootstrap_url="https://x")
    assert result == nested
    assert nested.exists()


def test_save_empty_urls_returns_none(cache_dir):
    """Writing an empty snapshot would confuse a future read
    into thinking there are no fallbacks -- so we don't."""
    assert url_cache.save({"urls": []}, bootstrap_url="https://x") is None
    assert not cache_dir.exists()


def test_save_missing_urls_key_returns_none(cache_dir):
    assert url_cache.save({"other": "stuff"}, bootstrap_url="https://x") is None


def test_save_skips_dicts_without_url(cache_dir):
    """Half-broken entries (no ``url``) must be dropped, not
    written as ``null`` -- else load() would surface bad URLs."""
    cfg = {"urls": [
        {"provider": "tailscale", "url": "https://ok.example"},
        {"provider": "broken"},  # missing url
        {"provider": "also-broken", "url": ""},  # empty url
    ]}
    url_cache.save(cfg, bootstrap_url="https://ok.example")
    loaded = url_cache.load()
    assert len(loaded["urls"]) == 1
    assert loaded["urls"][0]["url"] == "https://ok.example"


def test_save_atomic_leaves_no_tmp_file(cache_dir):
    url_cache.save(
        {"urls": [{"provider": "x", "url": "https://x"}]},
        bootstrap_url="https://x",
    )
    assert not list(cache_dir.parent.glob("*.tmp"))


# ---------------------------------------------------------------------------
# Disable flag interactions
# ---------------------------------------------------------------------------
def test_save_no_op_when_disabled(cache_dir, monkeypatch):
    monkeypatch.setenv("ARENA_BRIDGE_URL_CACHE", "0")
    result = url_cache.save(
        {"urls": [{"provider": "x", "url": "https://x"}]},
        bootstrap_url="https://x",
    )
    assert result is None
    assert not cache_dir.exists()


def test_load_no_op_when_disabled(cache_dir, monkeypatch):
    # Prime cache while enabled, then disable and try to load.
    url_cache.save({"urls": [{"provider": "x", "url": "https://x"}]},
                   bootstrap_url="https://x")
    assert cache_dir.exists()
    monkeypatch.setenv("ARENA_BRIDGE_URL_CACHE", "0")
    assert url_cache.load() is None


def test_clear_no_op_when_disabled(cache_dir, monkeypatch):
    # Prime cache while enabled.
    url_cache.save({"urls": [{"provider": "x", "url": "https://x"}]},
                   bootstrap_url="https://x")
    monkeypatch.setenv("ARENA_BRIDGE_URL_CACHE", "0")
    # clear() returns False and doesn't touch the file.
    assert url_cache.clear() is False
    assert cache_dir.exists()


# ---------------------------------------------------------------------------
# load() fault tolerance
# ---------------------------------------------------------------------------
def test_load_absent_file_returns_none(cache_dir):
    assert not cache_dir.exists()
    assert url_cache.load() is None


def test_load_malformed_json_returns_none(cache_dir):
    cache_dir.parent.mkdir(parents=True, exist_ok=True)
    cache_dir.write_text("{not json at all", encoding="utf-8")
    # No exception -- just None.
    assert url_cache.load() is None


def test_load_wrong_schema_version_returns_none(cache_dir):
    cache_dir.parent.mkdir(parents=True, exist_ok=True)
    cache_dir.write_text(
        json.dumps({
            "version": 9999,
            "saved_at": 1,
            "bootstrap_url": "x",
            "urls": [{"provider": "x", "url": "https://x"}],
        }),
        encoding="utf-8",
    )
    assert url_cache.load() is None


def test_load_urls_not_a_list_returns_none(cache_dir):
    cache_dir.parent.mkdir(parents=True, exist_ok=True)
    cache_dir.write_text(
        json.dumps({
            "version": url_cache.CACHE_VERSION,
            "saved_at": 1,
            "bootstrap_url": "x",
            "urls": "should have been a list",
        }),
        encoding="utf-8",
    )
    assert url_cache.load() is None


def test_load_empty_urls_returns_none(cache_dir):
    cache_dir.parent.mkdir(parents=True, exist_ok=True)
    cache_dir.write_text(
        json.dumps({
            "version": url_cache.CACHE_VERSION,
            "saved_at": 1,
            "bootstrap_url": "x",
            "urls": [],
        }),
        encoding="utf-8",
    )
    # Empty cache is semantically the same as no cache -- both mean
    # "no fallback URLs available".
    assert url_cache.load() is None


def test_load_root_not_a_dict_returns_none(cache_dir):
    cache_dir.parent.mkdir(parents=True, exist_ok=True)
    cache_dir.write_text('["a", "list", "not a dict"]', encoding="utf-8")
    assert url_cache.load() is None


# ---------------------------------------------------------------------------
# clear()
# ---------------------------------------------------------------------------
def test_clear_removes_existing_file(cache_dir):
    url_cache.save({"urls": [{"provider": "x", "url": "https://x"}]},
                   bootstrap_url="https://x")
    assert cache_dir.exists()
    assert url_cache.clear() is True
    assert not cache_dir.exists()


def test_clear_missing_file_returns_false(cache_dir):
    """rm -f semantics -- no file, no error, return False."""
    assert url_cache.clear() is False


# ---------------------------------------------------------------------------
# fallback_bootstrap_urls
# ---------------------------------------------------------------------------
def test_fallback_urls_preserves_priority_order(cache_dir):
    url_cache.save({"urls": [
        {"provider": "tailscale", "url": "https://a"},
        {"provider": "zerotier", "url": "http://b"},
        {"provider": "ngrok", "url": "https://c"},
    ]}, bootstrap_url="https://a")
    assert url_cache.fallback_bootstrap_urls() == [
        "https://a", "http://b", "https://c"
    ]


def test_fallback_urls_dedupes(cache_dir):
    """If for some weird reason the same URL appeared twice in the
    server response, we still emit it once so the fallback loop
    doesn't burn two timeouts on the same host."""
    url_cache.save({"urls": [
        {"provider": "x", "url": "https://a"},
        {"provider": "y", "url": "https://a"},  # dupe
        {"provider": "z", "url": "https://b"},
    ]}, bootstrap_url="https://a")
    assert url_cache.fallback_bootstrap_urls() == ["https://a", "https://b"]


def test_fallback_urls_empty_when_no_cache(cache_dir):
    assert url_cache.fallback_bootstrap_urls() == []


def test_fallback_urls_accepts_inline_cfg_dict():
    """Passing an in-memory dict lets tests bypass the filesystem."""
    urls = url_cache.fallback_bootstrap_urls({
        "urls": [
            {"provider": "x", "url": "https://one"},
            {"provider": "y", "url": "https://two"},
        ],
    })
    assert urls == ["https://one", "https://two"]


def test_fallback_urls_disabled_returns_empty(cache_dir, monkeypatch):
    url_cache.save({"urls": [{"provider": "x", "url": "https://a"}]},
                   bootstrap_url="https://a")
    monkeypatch.setenv("ARENA_BRIDGE_URL_CACHE", "0")
    assert url_cache.fallback_bootstrap_urls() == []
