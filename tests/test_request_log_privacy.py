"""v4.44.0 tests for the ARENA_LOG_PEER privacy dial + the
chmod 0o600 enforcement on requests.jsonl.
"""
from __future__ import annotations

import json
import os
import stat
import threading

import pytest

from arena.observability import request_log
from arena.observability.request_log import (
    _mask_peer,
    _peer_privacy_mode,
    log_request_response,
)


# ---------------------------------------------------------------------------
# _peer_privacy_mode env resolution
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("val,expected", [
    ("", "full"),
    ("full", "full"),
    ("garbage", "full"),
    ("mask", "mask"),
    ("MASK", "mask"),
    ("off", "off"),
    ("OFF", "off"),
    ("0", "off"),
    ("false", "off"),
    ("no", "off"),
])
def test_peer_privacy_mode(monkeypatch, val, expected):
    monkeypatch.setenv("ARENA_LOG_PEER", val)
    assert _peer_privacy_mode() == expected


def test_peer_privacy_mode_unset_defaults_full(monkeypatch):
    monkeypatch.delenv("ARENA_LOG_PEER", raising=False)
    assert _peer_privacy_mode() == "full"


# ---------------------------------------------------------------------------
# _mask_peer determinism + salt sensitivity
# ---------------------------------------------------------------------------
def test_mask_peer_is_deterministic(monkeypatch):
    monkeypatch.setenv("ARENA_LOG_PEER_SALT", "test-salt")
    a1 = _mask_peer("10.57.152.120")
    a2 = _mask_peer("10.57.152.120")
    assert a1 == a2


def test_mask_peer_different_ips_get_different_hashes(monkeypatch):
    monkeypatch.setenv("ARENA_LOG_PEER_SALT", "test-salt")
    assert _mask_peer("10.57.152.120") != _mask_peer("10.57.152.121")


def test_mask_peer_different_salts_get_different_hashes(monkeypatch):
    monkeypatch.setenv("ARENA_LOG_PEER_SALT", "salt-a")
    a = _mask_peer("10.0.0.1")
    monkeypatch.setenv("ARENA_LOG_PEER_SALT", "salt-b")
    b = _mask_peer("10.0.0.1")
    assert a != b


def test_mask_peer_output_shape(monkeypatch):
    """Enough entropy to distinguish peers, short enough to
    stay readable in a log tail. Shape check locks the format
    in: ``peer:`` prefix + 12 hex chars."""
    monkeypatch.setenv("ARENA_LOG_PEER_SALT", "s")
    out = _mask_peer("1.2.3.4")
    assert out.startswith("peer:")
    assert len(out) == len("peer:") + 12


def test_mask_peer_does_not_leak_original(monkeypatch):
    """The masked form must never contain any dotted-quad
    fragment of the input -- a partial-substring leak would
    let a co-tenant grep for their own IP suffix."""
    monkeypatch.setenv("ARENA_LOG_PEER_SALT", "s")
    ip = "10.57.152.120"
    out = _mask_peer(ip)
    for part in ip.split("."):
        assert part not in out, f"leak: {part!r} appears in {out!r}"


# ---------------------------------------------------------------------------
# log_request_response -- privacy modes end-to-end
# ---------------------------------------------------------------------------
@pytest.fixture
def log_setup(tmp_path, monkeypatch):
    monkeypatch.delenv("ARENA_LOG_PEER", raising=False)
    monkeypatch.delenv("ARENA_LOG_PEER_SALT", raising=False)
    return tmp_path, tmp_path / "requests.jsonl"


def _write_one(log_file, peer="10.0.0.1"):
    log_request_response(
        log_file=log_file,
        app_dir=log_file.parent,
        utc_now_fn=lambda: "2026-07-17T00:00:00Z",
        method="GET",
        path="/health",
        status=200,
        duration=0.01,
        req_id="abc",
        peer=peer,
    )


def _read_last_entry(log_file):
    return json.loads(log_file.read_text().strip().splitlines()[-1])


def test_default_mode_records_full_peer(log_setup):
    _, log_file = log_setup
    _write_one(log_file, peer="10.0.0.42")
    entry = _read_last_entry(log_file)
    assert entry["peer"] == "10.0.0.42"


def test_off_mode_omits_peer_field(log_setup, monkeypatch):
    _, log_file = log_setup
    monkeypatch.setenv("ARENA_LOG_PEER", "0")
    _write_one(log_file, peer="10.0.0.42")
    entry = _read_last_entry(log_file)
    assert "peer" not in entry, (
        "off mode must omit the peer field entirely, not blank it"
    )


def test_mask_mode_hashes_peer(log_setup, monkeypatch):
    _, log_file = log_setup
    monkeypatch.setenv("ARENA_LOG_PEER", "mask")
    monkeypatch.setenv("ARENA_LOG_PEER_SALT", "test-salt")
    _write_one(log_file, peer="10.0.0.42")
    entry = _read_last_entry(log_file)
    assert entry["peer"].startswith("peer:")
    # Verify no dotted-quad fragment leaked.
    for part in "10.0.0.42".split("."):
        assert part not in entry["peer"]


def test_missing_peer_never_writes_field(log_setup):
    _, log_file = log_setup
    _write_one(log_file, peer="")
    entry = _read_last_entry(log_file)
    assert "peer" not in entry


# ---------------------------------------------------------------------------
# chmod 0o600 on the log file
# ---------------------------------------------------------------------------
@pytest.mark.skipif(os.name == "nt", reason="POSIX mode bits only")
def test_log_file_is_mode_600(log_setup):
    _, log_file = log_setup
    _write_one(log_file, peer="1.2.3.4")
    mode = stat.S_IMODE(os.stat(log_file).st_mode)
    assert mode == 0o600, (
        f"requests.jsonl must be 0o600, got {oct(mode)}. Pre-v4.44.0 "
        "was 0o644 which meant any co-tenant could read the operator's "
        "HTTP history."
    )
