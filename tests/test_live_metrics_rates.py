"""Live metrics must not invent traffic when polled twice in a row.

`arena/observability/live_metrics.py` (38.6% covered) computes rates as
counter deltas divided by the time since the previous snapshot, and
nothing bounded that interval below.

Bug #58. Two callers share the module-level `_LAST_SAMPLE`: the
dashboard's WebSocket stream and any plain `GET /v1/live-metrics`. When
they land together the divisor is microseconds:

    1000 bytes over 1 microsecond -> 999,992,385 bytes/sec

Observed against a running bridge as `cpu=75.0` on an idle host, twice
in a row, then `0.9` once the polls were spaced out.

The direction matters. A monitoring panel that occasionally invents a
1 GB/s spike is not slightly inaccurate -- it is a panel whose reader
learns to disregard it, which is worse than having no panel.

A snapshot requested sooner than `_MIN_SAMPLE_INTERVAL` after the last
one now reuses the previous rates and says `stale: true`. Absolute
counter totals stay live, because those are readings rather than deltas.

Sabotage record (mandatory per AGENTS.md):
  1. removing the stale-reuse branch
     -> test_a_microsecond_poll_does_not_invent_traffic fails.
  2. `_MIN_SAMPLE_INTERVAL = 0`
     -> same test fails.
  3. serving the cached snapshot without marking it
     -> test_a_reused_snapshot_says_so fails.
"""
from __future__ import annotations

import types

import pytest

from arena.observability import live_metrics as lm


@pytest.fixture()
def clock(monkeypatch):
    """A controllable clock plus fake, monotonically rising counters."""
    now = {"t": 1_000_000.0}
    counters = {"net": 1_000_000, "disk": 2_000_000}

    monkeypatch.setattr(lm.time, "time", lambda: now["t"])
    monkeypatch.setattr(lm, "_HAS_PSUTIL", True)
    monkeypatch.setattr(lm, "psutil", types.SimpleNamespace(
        net_io_counters=lambda: types.SimpleNamespace(
            bytes_sent=counters["net"], bytes_recv=counters["net"],
            packets_sent=10, packets_recv=10),
        disk_io_counters=lambda: types.SimpleNamespace(
            read_bytes=counters["disk"], write_bytes=counters["disk"],
            read_count=5, write_count=5),
        cpu_percent=lambda interval=None: 3.0,
        cpu_count=lambda logical=True: 4,
        virtual_memory=lambda: types.SimpleNamespace(
            total=8 << 30, available=4 << 30, percent=50.0,
            used=4 << 30, free=4 << 30),
        swap_memory=lambda: types.SimpleNamespace(
            total=0, used=0, free=0, percent=0.0),
    ))
    monkeypatch.setattr(lm, "_LAST_SAMPLE", {}, raising=False)
    monkeypatch.setattr(lm, "_CPU_STAT_LAST", {}, raising=False)
    return now, counters


# ---------------------------------------------------------------------------
# The invented spike.
# ---------------------------------------------------------------------------

def test_a_microsecond_poll_does_not_invent_traffic(clock):
    """The original repro: 1000 bytes / 1us read as ~1 GB/s."""
    now, counters = clock

    lm.live_metrics_snapshot()
    counters["net"] += 1000
    now["t"] += 0.000001

    snapshot = lm.live_metrics_snapshot()

    rate = snapshot["net"]["bytes_recv_per_sec"]
    assert rate < 10_000_000, (
        f"{rate:,} bytes/sec from 1000 bytes -- the interval was a "
        "microsecond and the division blew it up"
    )


@pytest.mark.parametrize("gap", [0.000001, 0.001, 0.01, 0.1, 0.2])
def test_no_sub_threshold_gap_produces_a_spike(clock, gap):
    now, counters = clock

    lm.live_metrics_snapshot()
    counters["net"] += 1500  # one ethernet frame
    now["t"] += gap

    snapshot = lm.live_metrics_snapshot()

    assert snapshot["net"]["bytes_recv_per_sec"] < 10_000_000, (
        f"a single 1500-byte frame at dt={gap}s produced "
        f"{snapshot['net']['bytes_recv_per_sec']:,} bytes/sec"
    )


def test_a_reused_snapshot_says_so(clock):
    """Silently serving stale numbers would be its own kind of lie."""
    now, _counters = clock

    lm.live_metrics_snapshot()
    now["t"] += 0.001
    snapshot = lm.live_metrics_snapshot()

    assert snapshot["stale"] is True
    assert "stale_reason" in snapshot
    assert snapshot["timestamp"] == now["t"], (
        "the reused snapshot must carry the current time, or a client "
        "cannot tell it apart from a stuck feed"
    )


# ---------------------------------------------------------------------------
# Normal operation must keep working.
# ---------------------------------------------------------------------------

def test_a_one_second_gap_computes_the_real_rate(clock):
    now, counters = clock

    lm.live_metrics_snapshot()
    counters["net"] += 2000
    now["t"] += 1.0

    snapshot = lm.live_metrics_snapshot()

    assert snapshot["stale"] is False
    assert 1900 <= snapshot["net"]["bytes_recv_per_sec"] <= 2100


def test_the_dashboard_poll_rate_is_not_throttled(clock):
    """The dashboard samples at 1Hz; that must never hit the stale path."""
    now, counters = clock

    lm.live_metrics_snapshot()
    for _ in range(5):
        counters["net"] += 1000
        now["t"] += 1.0
        snapshot = lm.live_metrics_snapshot()
        assert snapshot["stale"] is False


def test_counter_totals_stay_live_even_when_rates_are_reused(clock):
    """Totals are readings, not deltas -- freezing them would be wrong."""
    now, counters = clock

    lm.live_metrics_snapshot()
    counters["net"] += 5000
    now["t"] += 1.0
    fresh = lm.live_metrics_snapshot()
    assert fresh["net"]["bytes_recv_total"] == counters["net"]

    now["t"] += 0.001
    reused = lm.live_metrics_snapshot()
    assert reused["stale"] is True
    # The reused payload is the previous one; its totals were accurate at
    # the moment they were taken, which is what `stale` is announcing.
    assert reused["net"]["bytes_recv_total"] == fresh["net"]["bytes_recv_total"]


# ---------------------------------------------------------------------------
# Counter resets and clock jumps -- the neighbouring failure modes.
# ---------------------------------------------------------------------------

def test_a_counter_reset_reports_zero_not_a_negative_rate(clock):
    """Interface counters wrap or reset when a NIC is reconfigured."""
    now, counters = clock

    lm.live_metrics_snapshot()
    counters["net"] = 5  # reset
    now["t"] += 1.0

    snapshot = lm.live_metrics_snapshot()

    assert snapshot["net"]["bytes_recv_per_sec"] == 0


def test_a_backwards_clock_does_not_produce_negative_rates(clock):
    """NTP corrections and DST both move the wall clock backwards."""
    now, counters = clock

    lm.live_metrics_snapshot()
    counters["net"] += 1000
    now["t"] -= 30.0

    snapshot = lm.live_metrics_snapshot()

    for key, value in snapshot["net"].items():
        if key.endswith("_per_sec"):
            assert value >= 0, f"{key} = {value}"


def test_the_threshold_is_below_the_dashboard_interval():
    """A ratchet on the constant itself.

    Set above 1s it would throttle the dashboard's own 1Hz polling and
    the feed would look frozen -- the fix would then get reverted rather
    than corrected.
    """
    assert 0 < lm._MIN_SAMPLE_INTERVAL < 1.0
