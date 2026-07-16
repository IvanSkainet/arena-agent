"""Tests for the tunnels_probe circuit breaker (v4.8.0).

Covers the standalone :mod:`arena.admin.tunnels_breaker` state
machine (deterministic clock) and its integration into
:func:`arena.admin.tunnels.tunnels_probe` (skipping probes when
the breaker is open, snapshot in the response payload).
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from arena.admin.tunnels_breaker import (  # noqa: E402
    BreakerRecord,
    TunnelsBreaker,
    get_default_breaker,
    reset_default_breaker,
)


class _FakeClock:
    """Deterministic monotonic-like clock so tests never race real
    time. Only implements what the breaker calls (a no-arg __call__)."""

    def __init__(self, start: float = 0.0):
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, sec: float) -> None:
        self.now += sec


# ---------------------------------------------------------------------------
# State machine
# ---------------------------------------------------------------------------
def test_breaker_starts_closed_for_unknown_key():
    b = TunnelsBreaker(threshold=3, cooldown=60.0, clock=_FakeClock())
    assert b.allow("cloudflared|foo:443") is True
    assert b.describe_open("cloudflared|foo:443") is None


def test_breaker_opens_after_threshold_consecutive_failures():
    clock = _FakeClock()
    b = TunnelsBreaker(threshold=3, cooldown=60.0, clock=clock)
    k = "cloudflared|foo:443"
    b.record_failure(k, error="timeout after 1.5s")
    assert b.allow(k) is True
    b.record_failure(k, error="timeout after 1.5s")
    assert b.allow(k) is True
    b.record_failure(k, error="timeout after 1.5s")
    # Third consecutive failure trips the breaker.
    assert b.allow(k) is False
    reason = b.describe_open(k)
    assert reason is not None
    assert "3 consecutive failures" in reason
    assert "cools down in 60s" in reason
    assert "timeout after 1.5s" in reason


def test_breaker_success_resets_counter_before_opening():
    """A single success anywhere in the run must reset the counter --
    otherwise a flaky provider that alternates would eventually trip
    even though it works every other call."""
    b = TunnelsBreaker(threshold=3, cooldown=60.0, clock=_FakeClock())
    k = "cloudflared|foo:443"
    b.record_failure(k, error="e")
    b.record_failure(k, error="e")
    b.record_success(k)
    b.record_failure(k, error="e")
    b.record_failure(k, error="e")
    # 2 fails + success + 2 fails -- counter is 2, still under 3.
    assert b.allow(k) is True


def test_breaker_cooldown_transitions_to_half_open_then_success_closes():
    clock = _FakeClock()
    b = TunnelsBreaker(threshold=3, cooldown=60.0, clock=clock)
    k = "cloudflared|foo:443"
    for _ in range(3):
        b.record_failure(k, error="timeout")
    assert b.allow(k) is False

    # Half-way through cooldown, still open.
    clock.advance(30)
    assert b.allow(k) is False

    # Cooldown elapsed -> half-open (allow() returns True).
    clock.advance(31)
    assert b.allow(k) is True

    # A success in half-open closes the breaker for good.
    b.record_success(k)
    assert b.allow(k) is True
    assert b.describe_open(k) is None
    snap = b.snapshot()[k]
    assert snap["state"] == "closed"
    assert snap["consecutive_failures"] == 0


def test_breaker_half_open_failure_reopens_immediately():
    """After cooldown a single failure must re-open the breaker
    right away (we keep the counter at threshold when opening)."""
    clock = _FakeClock()
    b = TunnelsBreaker(threshold=3, cooldown=60.0, clock=clock)
    k = "cloudflared|foo:443"
    for _ in range(3):
        b.record_failure(k, error="timeout")
    clock.advance(61)
    assert b.allow(k) is True                 # half-open
    b.record_failure(k, error="still bad")
    assert b.allow(k) is False                 # re-opened
    assert "still bad" in b.describe_open(k)


def test_breaker_snapshot_shape_is_json_safe():
    clock = _FakeClock()
    b = TunnelsBreaker(threshold=2, cooldown=30.0, clock=clock)
    b.record_failure("cloudflared|a:1", error="oops")
    b.record_failure("cloudflared|a:1", error="oops")
    b.record_success("tailscale|b:2")
    snap = b.snapshot()
    assert set(snap["cloudflared|a:1"]) >= {
        "state", "consecutive_failures", "last_error", "cools_down_in_sec",
    }
    assert snap["cloudflared|a:1"]["state"] == "open"
    assert snap["cloudflared|a:1"]["consecutive_failures"] == 2
    assert snap["cloudflared|a:1"]["last_error"] == "oops"
    assert snap["cloudflared|a:1"]["cools_down_in_sec"] == pytest.approx(30.0, abs=0.001)
    # cools_down_in_sec only present when open.
    assert snap["tailscale|b:2"]["state"] == "closed"
    assert "cools_down_in_sec" not in snap["tailscale|b:2"]


def test_breaker_reset_clears_state():
    b = TunnelsBreaker(threshold=2, cooldown=30.0, clock=_FakeClock())
    b.record_failure("a", error="x")
    b.record_failure("a", error="x")
    assert b.allow("a") is False
    b.reset("a")
    assert b.allow("a") is True
    b.record_failure("a", error="x"); b.record_failure("a", error="x")
    b.record_failure("b", error="y"); b.record_failure("b", error="y")
    b.reset()
    assert b.snapshot() == {}


def test_breaker_disable_env_bypasses_state(monkeypatch):
    """ARENA_BREAKER_DISABLE turns the breaker into a no-op so
    operators debugging a genuine provider issue can force probes
    through without a bridge restart."""
    b = TunnelsBreaker(threshold=1, cooldown=999.0, clock=_FakeClock())
    b.record_failure("k", error="e")
    assert b.allow("k") is False
    monkeypatch.setenv("ARENA_BREAKER_DISABLE", "1")
    assert b.allow("k") is True
    assert b.describe_open("k") is None
    monkeypatch.delenv("ARENA_BREAKER_DISABLE")
    assert b.allow("k") is False   # still open once env cleared


def test_breaker_threshold_and_cooldown_from_env(monkeypatch):
    """Env overrides apply to the module-level singleton on
    ``reset_default_breaker()`` + next ``get_default_breaker()``."""
    monkeypatch.setenv("ARENA_BREAKER_THRESHOLD", "5")
    monkeypatch.setenv("ARENA_BREAKER_COOLDOWN", "12")
    reset_default_breaker()
    b = get_default_breaker()
    assert b.threshold == 5
    assert b.cooldown == 12.0
    reset_default_breaker()   # leave a clean slate for other tests


def test_breaker_env_clamps_to_safe_bounds(monkeypatch):
    """Threshold is clamped 1..20 and cooldown to at least 1s so a
    typo (`ARENA_BREAKER_THRESHOLD=0`) can't make the breaker
    permanently open or the cooldown negative."""
    monkeypatch.setenv("ARENA_BREAKER_THRESHOLD", "0")
    monkeypatch.setenv("ARENA_BREAKER_COOLDOWN", "-5")
    reset_default_breaker()
    b = get_default_breaker()
    assert b.threshold == 1        # clamped up
    assert b.cooldown == 1.0       # clamped up
    reset_default_breaker()


# ---------------------------------------------------------------------------
# Integration with tunnels_probe
# ---------------------------------------------------------------------------
def _stub_status(providers):
    """tunnels_status stub that returns whatever ``providers`` list
    we hand it, matching the shape tunnels_probe iterates over."""
    def _inner(**_kw):
        return {"priority": tuple(p["provider"] for p in providers),
                "providers": providers}
    return _inner


def test_probe_reports_breaker_snapshot_field():
    """v4.8.0 contract: the probe response always includes a
    ``breaker`` dict (empty when no history)."""
    from arena.admin import tunnels as tmod
    # Fresh breaker, but stub tunnels_status to return zero providers
    # so we don't touch the network.
    breaker = TunnelsBreaker(threshold=3, cooldown=60.0, clock=_FakeClock())
    result = tmod.tunnels_probe(
        sys_funnel_status_sync=lambda: {"ok": True, "active": False},
        cloudflared_status_sync=lambda: {"ok": True, "active": False},
        zerotier_status_sync=lambda: {"ok": True, "backend": "none",
                                       "installed": False,
                                       "zerotier": {}, "networks": []},
        breaker=breaker,
    )
    assert result["ok"] is True
    assert "breaker" in result
    assert isinstance(result["breaker"], dict)


def test_probe_skips_open_provider_with_reason(monkeypatch):
    """When the breaker for a provider is open, tunnels_probe must
    NOT call _probe_tcp for it, and must surface skip_reason +
    breaker_state='open' in the entry."""
    from arena.admin import tunnels as tmod

    # Force a provider list with a plain-http URL so tunnels_probe
    # goes through the TCP-probe branch (breaker only applies there;
    # https URLs are trusted from the active flag).
    def _stub(**_kw):
        return {
            "priority": ("cloudflared",),
            "providers": [{
                "provider": "cloudflared",
                "public_url": "http://stuck.example:9999/",
                "active": True,
                "public_kind": "http",
            }],
        }
    monkeypatch.setattr(tmod, "tunnels_status", _stub)

    called = {"n": 0}
    def _refuse(*_a, **_kw):
        called["n"] += 1
        return {"ok": False, "error": "should not be called",
                "duration_ms": 0}
    monkeypatch.setattr(tmod, "_probe_tcp", _refuse)

    # Pre-open the breaker for the exact key tunnels_probe builds.
    breaker = TunnelsBreaker(threshold=1, cooldown=60.0, clock=_FakeClock())
    breaker.record_failure("cloudflared|stuck.example:9999",
                           error="timeout after 1.5s")

    result = tmod.tunnels_probe(breaker=breaker,
                                sys_funnel_status_sync=lambda: {},
                                cloudflared_status_sync=lambda: {},
                                zerotier_status_sync=lambda: {})
    assert called["n"] == 0
    entry = result["probes"][0]
    assert entry["provider"] == "cloudflared"
    assert entry["reachable"] is False
    assert entry["breaker_state"] == "open"
    assert entry["skip_reason"] is not None
    assert "circuit-breaker" in entry["skip_reason"]
    # timeout text propagates from the last recorded failure error.
    assert "timeout after 1.5s" in entry["skip_reason"]


def test_probe_records_success_closing_the_breaker(monkeypatch):
    from arena.admin import tunnels as tmod

    def _stub(**_kw):
        return {
            "priority": ("cloudflared",),
            "providers": [{
                "provider": "cloudflared",
                "public_url": "http://ok.example:8080/",
                "active": True,
                "public_kind": "http",
            }],
        }
    monkeypatch.setattr(tmod, "tunnels_status", _stub)
    monkeypatch.setattr(tmod, "_probe_tcp",
                        lambda *a, **kw: {"ok": True, "duration_ms": 7})

    breaker = TunnelsBreaker(threshold=2, cooldown=60.0, clock=_FakeClock())
    breaker.record_failure("cloudflared|ok.example:8080", error="e")
    breaker.record_failure("cloudflared|ok.example:8080", error="e")
    assert breaker.allow("cloudflared|ok.example:8080") is False

    # A successful probe (need to reset the open state first by
    # advancing time or via ARENA_BREAKER_DISABLE) -- easier path:
    # give breaker a fresh clock that already passed cooldown.
    fake = _FakeClock(start=120.0)
    breaker._clock = fake
    result = tmod.tunnels_probe(breaker=breaker,
                                sys_funnel_status_sync=lambda: {},
                                cloudflared_status_sync=lambda: {},
                                zerotier_status_sync=lambda: {})
    entry = result["probes"][0]
    assert entry["reachable"] is True
    snap = result["breaker"]["cloudflared|ok.example:8080"]
    assert snap["state"] == "closed"
    assert snap["consecutive_failures"] == 0


def test_probe_records_failure_incrementing_counter(monkeypatch):
    from arena.admin import tunnels as tmod

    def _stub(**_kw):
        return {
            "priority": ("cloudflared",),
            "providers": [{
                "provider": "cloudflared",
                "public_url": "http://flaky.example:8080/",
                "active": True,
                "public_kind": "http",
            }],
        }
    monkeypatch.setattr(tmod, "tunnels_status", _stub)
    monkeypatch.setattr(tmod, "_probe_tcp",
                        lambda *a, **kw: {"ok": False,
                                          "error": "timeout after 1.5s",
                                          "duration_ms": 1500})

    breaker = TunnelsBreaker(threshold=3, cooldown=60.0, clock=_FakeClock())
    for _ in range(2):
        tmod.tunnels_probe(breaker=breaker,
                           sys_funnel_status_sync=lambda: {},
                           cloudflared_status_sync=lambda: {},
                           zerotier_status_sync=lambda: {})
    # Two failures recorded -- one more should open the breaker.
    third = tmod.tunnels_probe(breaker=breaker,
                               sys_funnel_status_sync=lambda: {},
                               cloudflared_status_sync=lambda: {},
                               zerotier_status_sync=lambda: {})
    # The third probe itself still ran (it was the one that hit the
    # threshold). Fourth call should be skipped.
    snap = third["breaker"]["cloudflared|flaky.example:8080"]
    assert snap["state"] == "open"
    assert snap["consecutive_failures"] == 3


def test_probe_key_includes_host_and_port_so_url_moves_reset_state():
    """A new host or port must get a fresh breaker record so a
    Cloudflared reissue with a different quick-tunnel hostname
    doesn't inherit the previous URL's failure history."""
    b = TunnelsBreaker(threshold=1, cooldown=60.0, clock=_FakeClock())
    b.record_failure("cloudflared|old.example:443", error="e")
    assert b.allow("cloudflared|old.example:443") is False
    # New host, same provider -> fresh state.
    assert b.allow("cloudflared|new.example:443") is True
    # Same host, different port -> fresh state.
    assert b.allow("cloudflared|old.example:8443") is True
