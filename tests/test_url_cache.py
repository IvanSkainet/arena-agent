"""Tests for the v4.39.0 persistent URL memory module,
extended with the v4.40.0 security hardening (HMAC signature,
URL allowlist, chmod 0o600).

Covers the ``arena/agentctl_cli/url_cache.py`` module in
isolation -- no bridge calls, no CLI subprocess. Integration
tests for the fallback loop itself live in
``tests/test_url_cache_fallback.py``.

Test surface:
  * v4.39.0 -- save() round-trips through load()
  * v4.39.0 -- cache location honours ARENA_URL_CACHE_PATH
  * v4.39.0 -- ARENA_BRIDGE_URL_CACHE truthy-off shapes disable cache
  * v4.39.0 -- empty urls list -> save() returns None (no empty snapshot)
  * v4.39.0 -- malformed on-disk file -> load() returns None silently
  * v4.39.0 -- schema version mismatch -> load() returns None silently
  * v4.39.0 -- atomic write leaves no .tmp file after normal run
  * v4.39.0 -- fallback_bootstrap_urls preserves order + dedupes
  * v4.39.0 -- clear() is idempotent + respects disable flag

  * v4.40.0 -- save() refuses to write without a secret
  * v4.40.0 -- load() refuses cache without a secret
  * v4.40.0 -- HMAC signature verified on load (mismatched -> None)
  * v4.40.0 -- tampered ``payload.urls`` invalidates the signature
  * v4.40.0 -- tampered ``sig`` field returns None
  * v4.40.0 -- v4.39.0-shaped unsigned files are refused (envelope check)
  * v4.40.0 -- URL scheme allowlist (http/https only) at write time
  * v4.40.0 -- URL host blocklist (metadata / localhost / .internal / .local)
  * v4.40.0 -- RFC1918 addresses accepted (ZeroTier compatibility)
  * v4.40.0 -- fallback_bootstrap_urls re-validates URLs at read time
  * v4.40.0 -- cache file written with mode 0o600 (POSIX only)
  * v4.40.0 -- constant-time signature comparison via hmac.compare_digest
"""
from __future__ import annotations

import json
import os
import stat
from pathlib import Path

import pytest

from arena.agentctl_cli import url_cache


# The secret used across the whole suite. Any string works --
# what matters is that save() and load() use the same one.
TEST_SECRET = "test-token-abc123"
OTHER_SECRET = "different-token-xyz789"


@pytest.fixture
def cache_dir(tmp_path, monkeypatch):
    """Redirect the cache to a per-test tmp directory so tests
    don't collide with each other or with a real user cache."""
    p = tmp_path / "last_urls.json"
    monkeypatch.setenv("ARENA_URL_CACHE_PATH", str(p))
    monkeypatch.delenv("ARENA_BRIDGE_URL_CACHE", raising=False)
    return p


def _save(cfg, *, bootstrap_url="https://ts.example",
          secret=TEST_SECRET):
    """Shortcut used by every round-trip test -- keeps the
    per-test noise low while ensuring the security-critical
    secret argument is always explicit."""
    return url_cache.save(cfg, bootstrap_url=bootstrap_url, secret=secret)


def _load(secret=TEST_SECRET):
    return url_cache.load(secret=secret)


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
    written = _save(cfg)
    assert written == cache_dir
    assert cache_dir.exists()

    loaded = _load()
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
    result = _save({"urls": [{"provider": "x", "url": "https://x"}]})
    assert result == nested
    assert nested.exists()


def test_save_empty_urls_returns_none(cache_dir):
    """Writing an empty snapshot would confuse a future read
    into thinking there are no fallbacks -- so we don't."""
    assert _save({"urls": []}) is None
    assert not cache_dir.exists()


def test_save_missing_urls_key_returns_none(cache_dir):
    assert _save({"other": "stuff"}) is None


def test_save_skips_dicts_without_url(cache_dir):
    """Half-broken entries (no ``url``) must be dropped, not
    written as ``null`` -- else load() would surface bad URLs."""
    cfg = {"urls": [
        {"provider": "tailscale", "url": "https://ok.example"},
        {"provider": "broken"},  # missing url
        {"provider": "also-broken", "url": ""},  # empty url
    ]}
    _save(cfg)
    loaded = _load()
    assert len(loaded["urls"]) == 1
    assert loaded["urls"][0]["url"] == "https://ok.example"


def test_save_atomic_leaves_no_tmp_file(cache_dir):
    _save({"urls": [{"provider": "x", "url": "https://x"}]})
    assert not list(cache_dir.parent.glob("*.tmp"))


# ---------------------------------------------------------------------------
# Disable flag interactions
# ---------------------------------------------------------------------------
def test_save_no_op_when_disabled(cache_dir, monkeypatch):
    monkeypatch.setenv("ARENA_BRIDGE_URL_CACHE", "0")
    result = _save({"urls": [{"provider": "x", "url": "https://x"}]})
    assert result is None
    assert not cache_dir.exists()


def test_load_no_op_when_disabled(cache_dir, monkeypatch):
    # Prime cache while enabled, then disable and try to load.
    _save({"urls": [{"provider": "x", "url": "https://x"}]})
    assert cache_dir.exists()
    monkeypatch.setenv("ARENA_BRIDGE_URL_CACHE", "0")
    assert _load() is None


def test_clear_no_op_when_disabled(cache_dir, monkeypatch):
    # Prime cache while enabled.
    _save({"urls": [{"provider": "x", "url": "https://x"}]})
    monkeypatch.setenv("ARENA_BRIDGE_URL_CACHE", "0")
    # clear() returns False and doesn't touch the file.
    assert url_cache.clear() is False
    assert cache_dir.exists()


# ---------------------------------------------------------------------------
# load() fault tolerance
# ---------------------------------------------------------------------------
def test_load_absent_file_returns_none(cache_dir):
    assert not cache_dir.exists()
    assert _load() is None


def test_load_malformed_json_returns_none(cache_dir):
    cache_dir.parent.mkdir(parents=True, exist_ok=True)
    cache_dir.write_text("{not json at all", encoding="utf-8")
    # No exception -- just None.
    assert _load() is None


def test_load_wrong_schema_version_returns_none(cache_dir):
    """A file with the right envelope but the wrong inner
    schema version is refused. The signature has to be valid
    too -- otherwise we'd bounce off the signature check first
    and never reach the version check."""
    cache_dir.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": 9999,
        "saved_at": 1,
        "bootstrap_url": "x",
        "urls": [{"provider": "x", "url": "https://x"}],
    }
    envelope = {
        "envelope_version": url_cache.ENVELOPE_VERSION,
        "sig": url_cache._sign(payload, TEST_SECRET),
        "payload": payload,
    }
    cache_dir.write_text(json.dumps(envelope), encoding="utf-8")
    assert _load() is None


def test_load_urls_not_a_list_returns_none(cache_dir):
    cache_dir.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": url_cache.CACHE_VERSION,
        "saved_at": 1,
        "bootstrap_url": "x",
        "urls": "should have been a list",
    }
    envelope = {
        "envelope_version": url_cache.ENVELOPE_VERSION,
        "sig": url_cache._sign(payload, TEST_SECRET),
        "payload": payload,
    }
    cache_dir.write_text(json.dumps(envelope), encoding="utf-8")
    assert _load() is None


def test_load_empty_urls_returns_none(cache_dir):
    cache_dir.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": url_cache.CACHE_VERSION,
        "saved_at": 1,
        "bootstrap_url": "x",
        "urls": [],
    }
    envelope = {
        "envelope_version": url_cache.ENVELOPE_VERSION,
        "sig": url_cache._sign(payload, TEST_SECRET),
        "payload": payload,
    }
    cache_dir.write_text(json.dumps(envelope), encoding="utf-8")
    # Empty cache is semantically the same as no cache -- both mean
    # "no fallback URLs available".
    assert _load() is None


def test_load_root_not_a_dict_returns_none(cache_dir):
    cache_dir.parent.mkdir(parents=True, exist_ok=True)
    cache_dir.write_text('["a", "list", "not a dict"]', encoding="utf-8")
    assert _load() is None


# ---------------------------------------------------------------------------
# clear()
# ---------------------------------------------------------------------------
def test_clear_removes_existing_file(cache_dir):
    _save({"urls": [{"provider": "x", "url": "https://x"}]})
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
    _save({"urls": [
        {"provider": "tailscale", "url": "https://a"},
        {"provider": "zerotier", "url": "http://b"},
        {"provider": "ngrok", "url": "https://c"},
    ]})
    assert url_cache.fallback_bootstrap_urls(secret=TEST_SECRET) == [
        "https://a", "http://b", "https://c"
    ]


def test_fallback_urls_dedupes(cache_dir):
    """If for some weird reason the same URL appeared twice in the
    server response, we still emit it once so the fallback loop
    doesn't burn two timeouts on the same host."""
    _save({"urls": [
        {"provider": "x", "url": "https://a"},
        {"provider": "y", "url": "https://a"},  # dupe
        {"provider": "z", "url": "https://b"},
    ]})
    assert url_cache.fallback_bootstrap_urls(secret=TEST_SECRET) == [
        "https://a", "https://b"
    ]


def test_fallback_urls_empty_when_no_cache(cache_dir):
    assert url_cache.fallback_bootstrap_urls(secret=TEST_SECRET) == []


def test_fallback_urls_accepts_inline_cfg_dict():
    """Passing an in-memory dict lets tests bypass the filesystem
    AND the HMAC path -- useful for the fast-path in fallback
    tests that already have the payload in hand."""
    urls = url_cache.fallback_bootstrap_urls({
        "urls": [
            {"provider": "x", "url": "https://one"},
            {"provider": "y", "url": "https://two"},
        ],
    })
    assert urls == ["https://one", "https://two"]


def test_fallback_urls_disabled_returns_empty(cache_dir, monkeypatch):
    _save({"urls": [{"provider": "x", "url": "https://a"}]})
    monkeypatch.setenv("ARENA_BRIDGE_URL_CACHE", "0")
    assert url_cache.fallback_bootstrap_urls(secret=TEST_SECRET) == []


# =============================================================================
# v4.40.0 SECURITY HARDENING
# =============================================================================

# ---------------------------------------------------------------------------
# HMAC signature -- write side
# ---------------------------------------------------------------------------
def test_save_refuses_without_secret(cache_dir):
    """A snapshot without a secret cannot be verified on load,
    so we refuse to write one in the first place. Callers that
    genuinely lack a token simply forgo the fallback."""
    result = url_cache.save(
        {"urls": [{"provider": "x", "url": "https://x"}]},
        bootstrap_url="https://x",
        secret=None,
    )
    assert result is None
    assert not cache_dir.exists()


def test_save_refuses_with_empty_secret(cache_dir):
    """Empty-string secret is treated the same as no secret --
    would produce a signature everyone could forge."""
    result = url_cache.save(
        {"urls": [{"provider": "x", "url": "https://x"}]},
        bootstrap_url="https://x",
        secret="",
    )
    assert result is None
    assert not cache_dir.exists()


def test_saved_envelope_has_expected_shape(cache_dir):
    """The on-disk layout is envelope_version + sig + payload.
    Any change to this shape is a breaking format change and
    should require bumping ENVELOPE_VERSION."""
    _save({"urls": [{"provider": "x", "url": "https://x"}]})
    envelope = json.loads(cache_dir.read_text(encoding="utf-8"))
    assert envelope["envelope_version"] == url_cache.ENVELOPE_VERSION
    assert isinstance(envelope["sig"], str)
    assert len(envelope["sig"]) == 64  # hex of SHA-256 -> 32 bytes -> 64 chars
    assert set(envelope["payload"].keys()) == {
        "version", "saved_at", "bootstrap_url", "urls"
    }


def test_saved_secret_never_appears_on_disk(cache_dir):
    """The secret itself must never touch the file -- only a
    derived HMAC of it. This guarantees an attacker with read
    access to the cache learns nothing about the token."""
    _save({"urls": [{"provider": "x", "url": "https://x"}]})
    on_disk = cache_dir.read_text(encoding="utf-8")
    assert TEST_SECRET not in on_disk


# ---------------------------------------------------------------------------
# HMAC signature -- load side
# ---------------------------------------------------------------------------
def test_load_refuses_without_secret(cache_dir):
    """A load call with no secret cannot verify the signature,
    so it must return None even though a well-formed file exists.
    This is the same threat model as an attacker with read-only
    access reading the cache but not knowing the token."""
    _save({"urls": [{"provider": "x", "url": "https://x"}]})
    assert cache_dir.exists()
    assert url_cache.load(secret=None) is None
    assert url_cache.load(secret="") is None


def test_load_refuses_wrong_secret(cache_dir):
    """The classic cache-poisoning scenario: attacker with write
    but not the token writes a plausible-looking snapshot. Our
    load rejects it because the signature won't verify against
    OUR token."""
    _save({"urls": [{"provider": "x", "url": "https://x"}]})
    assert cache_dir.exists()
    assert url_cache.load(secret=OTHER_SECRET) is None


def test_load_refuses_tampered_payload(cache_dir):
    """Attacker rewrites just the URLs field but leaves the
    signature alone. Signature mismatch -> None."""
    _save({"urls": [{"provider": "x", "url": "https://good.example"}]})
    envelope = json.loads(cache_dir.read_text(encoding="utf-8"))
    envelope["payload"]["urls"] = [
        {"provider": "x", "url": "https://attacker.example"}
    ]
    cache_dir.write_text(json.dumps(envelope), encoding="utf-8")
    assert _load() is None


def test_load_refuses_tampered_signature(cache_dir):
    """Attacker flips one bit of the sig field. Doesn't verify,
    return None."""
    _save({"urls": [{"provider": "x", "url": "https://x"}]})
    envelope = json.loads(cache_dir.read_text(encoding="utf-8"))
    # Flip the first hex character: '0' -> '1' or 'a' -> 'b'.
    sig = envelope["sig"]
    first = sig[0]
    envelope["sig"] = ("1" if first == "0" else "0") + sig[1:]
    cache_dir.write_text(json.dumps(envelope), encoding="utf-8")
    assert _load() is None


def test_load_refuses_v4_39_unsigned_file(cache_dir):
    """A file left over from v4.39.0 has no envelope wrapper --
    it's the raw payload with a bare ``version: 1``. The v4.40.0
    reader treats that as "no cache" because
    ``envelope_version`` is missing (and ``version: 1`` is also
    stale in the new numbering). This is what makes the upgrade
    security-safe: unsigned v4.39.0 snapshots are ignored, not
    trusted."""
    cache_dir.parent.mkdir(parents=True, exist_ok=True)
    v4_39_shape = {
        "version": 1,
        "saved_at": 1,
        "bootstrap_url": "https://old",
        "urls": [{"provider": "x", "url": "https://x"}],
    }
    cache_dir.write_text(json.dumps(v4_39_shape), encoding="utf-8")
    assert _load() is None


def test_load_refuses_wrong_envelope_version(cache_dir):
    """A future envelope version we don't understand is treated
    as no cache, so older clients never mis-interpret newer files."""
    cache_dir.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": url_cache.CACHE_VERSION,
        "saved_at": 1,
        "bootstrap_url": "x",
        "urls": [{"provider": "x", "url": "https://x"}],
    }
    envelope = {
        "envelope_version": 999,
        "sig": url_cache._sign(payload, TEST_SECRET),
        "payload": payload,
    }
    cache_dir.write_text(json.dumps(envelope), encoding="utf-8")
    assert _load() is None


def test_load_refuses_missing_sig_field(cache_dir):
    cache_dir.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": url_cache.CACHE_VERSION,
        "saved_at": 1,
        "bootstrap_url": "x",
        "urls": [{"provider": "x", "url": "https://x"}],
    }
    envelope = {
        "envelope_version": url_cache.ENVELOPE_VERSION,
        "payload": payload,
        # sig deliberately absent
    }
    cache_dir.write_text(json.dumps(envelope), encoding="utf-8")
    assert _load() is None


def test_load_refuses_non_string_sig(cache_dir):
    cache_dir.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": url_cache.CACHE_VERSION,
        "saved_at": 1,
        "bootstrap_url": "x",
        "urls": [{"provider": "x", "url": "https://x"}],
    }
    envelope = {
        "envelope_version": url_cache.ENVELOPE_VERSION,
        "sig": 12345,   # not a string
        "payload": payload,
    }
    cache_dir.write_text(json.dumps(envelope), encoding="utf-8")
    assert _load() is None


# ---------------------------------------------------------------------------
# URL allowlist -- write time
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("bad_url", [
    "ftp://foo/bar",              # non-http scheme
    "file:///etc/passwd",         # file:// obvious
    "gopher://old-school.example",  # anything else
    "javascript:alert(1)",        # DOM-XSS vector if UI ever renders
    "http://localhost:8080",      # SSRF classic
    "http://LocalHost/",          # case variant
    "http://metadata.google.internal/",   # GCP IMDS
    "http://169.254.169.254/latest/",     # AWS/GCP/Azure IMDS
    "http://foo.internal/",       # internal-suffix
    "http://foo.local/",          # mDNS
    "http://foo.localhost/",      # localhost subdomain
])
def test_save_skips_disallowed_urls(cache_dir, bad_url):
    """Bad URLs are silently dropped at write time. If ALL the
    provided URLs are bad, the whole write is refused (as though
    the caller passed an empty list)."""
    cfg = {"urls": [
        {"provider": "good", "url": "https://good.example"},
        {"provider": "bad", "url": bad_url},
    ]}
    _save(cfg)
    loaded = _load()
    assert loaded is not None
    assert len(loaded["urls"]) == 1
    assert loaded["urls"][0]["url"] == "https://good.example"


def test_save_refuses_when_all_urls_disallowed(cache_dir):
    cfg = {"urls": [
        {"provider": "x", "url": "http://localhost"},
        {"provider": "y", "url": "ftp://foo"},
    ]}
    assert _save(cfg) is None
    assert not cache_dir.exists()


def test_save_accepts_rfc1918_addresses(cache_dir):
    """ZeroTier's fallback URL is a private-network address
    (e.g. http://10.57.152.120:8765). We must NOT block it --
    that's the whole point of having ZT as a fallback."""
    cfg = {"urls": [
        {"provider": "zerotier", "url": "http://10.57.152.120:8765"},
        {"provider": "zerotier2", "url": "http://192.168.1.10:8765"},
        {"provider": "zerotier3", "url": "http://172.16.0.5:8765"},
    ]}
    _save(cfg)
    loaded = _load()
    assert loaded is not None
    assert len(loaded["urls"]) == 3


# ---------------------------------------------------------------------------
# URL allowlist -- read time (defence in depth)
# ---------------------------------------------------------------------------
def test_fallback_urls_rejects_disallowed_urls_at_read_time(cache_dir):
    """Even a validly-signed snapshot with a blocklisted URL
    (e.g. inserted by a token-holding insider) should not be
    followed. Simulate by writing the file directly with a
    valid signature but a metadata URL."""
    cache_dir.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": url_cache.CACHE_VERSION,
        "saved_at": 1,
        "bootstrap_url": "https://ok",
        "urls": [
            {"provider": "ok", "url": "https://ok.example"},
            {"provider": "trap", "url": "http://169.254.169.254/"},
        ],
    }
    envelope = {
        "envelope_version": url_cache.ENVELOPE_VERSION,
        "sig": url_cache._sign(payload, TEST_SECRET),
        "payload": payload,
    }
    cache_dir.write_text(json.dumps(envelope), encoding="utf-8")
    # The signed cache loads (signature matches) BUT the
    # SSRF-trap URL is filtered out at fallback resolution.
    loaded = _load()
    assert loaded is not None
    assert len(loaded["urls"]) == 2  # load doesn't filter
    fallback = url_cache.fallback_bootstrap_urls(secret=TEST_SECRET)
    assert fallback == ["https://ok.example"]  # fallback does


# ---------------------------------------------------------------------------
# File mode -- chmod 0o600
# ---------------------------------------------------------------------------
@pytest.mark.skipif(os.name == "nt", reason="POSIX mode bits only")
def test_saved_file_is_mode_600(cache_dir):
    """The cache file must be 0o600 so co-tenants on the machine
    can't read the URL list (which leaks Tailscale hostnames,
    ngrok reserved domains, and rotating cloudflared subdomains)."""
    _save({"urls": [{"provider": "x", "url": "https://x"}]})
    mode = stat.S_IMODE(os.stat(cache_dir).st_mode)
    assert mode == 0o600, f"expected 0o600, got {oct(mode)}"


@pytest.mark.skipif(os.name == "nt", reason="POSIX mode bits only")
def test_saved_parent_directory_is_mode_700(tmp_path, monkeypatch):
    """When we create ``~/.arena`` for the first time, tighten
    it to 0o700 too -- else the cache file mode is moot because
    the directory listing is readable by everyone."""
    nested = tmp_path / "brand-new-arena" / "last_urls.json"
    monkeypatch.setenv("ARENA_URL_CACHE_PATH", str(nested))
    monkeypatch.delenv("ARENA_BRIDGE_URL_CACHE", raising=False)
    _save({"urls": [{"provider": "x", "url": "https://x"}]})
    parent_mode = stat.S_IMODE(os.stat(nested.parent).st_mode)
    assert parent_mode == 0o700, f"expected 0o700, got {oct(parent_mode)}"


# ---------------------------------------------------------------------------
# Signature comparison is constant-time
# ---------------------------------------------------------------------------
def test_signature_check_uses_hmac_compare_digest(monkeypatch, cache_dir):
    """Sanity check: our load path routes signature comparison
    through hmac.compare_digest, not ``==``. Timing-leak defence
    is essentially free here but the discipline needs a test to
    stay locked in against future refactors."""
    import hmac as _hmac
    calls = {"n": 0}
    real = _hmac.compare_digest

    def counted(a, b):
        calls["n"] += 1
        return real(a, b)

    monkeypatch.setattr(url_cache.hmac, "compare_digest", counted)
    _save({"urls": [{"provider": "x", "url": "https://x"}]})
    _load()
    assert calls["n"] >= 1


# ---------------------------------------------------------------------------
# HMAC key derivation
# ---------------------------------------------------------------------------
def test_derive_key_is_deterministic():
    """Same secret -> same derived key. Otherwise save/load
    would randomly fail across calls."""
    assert url_cache._derive_key("abc") == url_cache._derive_key("abc")


def test_derive_key_differs_for_different_secrets():
    """Different secrets must yield different keys -- else the
    signature could collide for two different tokens."""
    assert url_cache._derive_key("abc") != url_cache._derive_key("abd")


def test_derive_key_length_is_32_bytes():
    """SHA-256 output is always 32 bytes."""
    assert len(url_cache._derive_key("anything")) == 32
