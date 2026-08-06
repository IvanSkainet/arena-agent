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


# --------------------------------------------------------------------
# v4.165.0 (bug #63). live_metrics.py came back from the first mutation
# sweep with 430 survivors out of 479 -- the tests pinned the extreme
# values (no 1 GB/s spikes) but never the ordinary arithmetic or the
# lifetime of the objects handed out. Two real defects were hiding in
# the rate-suppression path added for bug #58.
# --------------------------------------------------------------------


def test_a_stale_snapshot_does_not_alias_the_cache():
    """`dict(cached)` was a SHALLOW copy.

    Every nested section came back as the very object stored in
    _LAST_SAMPLE, so a caller writing to its own snapshot rewrote what
    the next caller would read. The dashboard poll and the WebSocket
    stream share this module-level state, which makes it cross-consumer
    corruption rather than an aliasing curiosity.
    """
    import arena.observability.live_metrics as lm

    first = lm.live_metrics_snapshot()
    stale = lm.live_metrics_snapshot()
    assert stale["stale"] is True, "expected the second poll to be suppressed"

    for section in ("cpu", "memory", "swap", "net", "disk", "gpu"):
        if isinstance(first.get(section), dict):
            assert stale[section] is not first[section], (
                f"{section} is the same object in two snapshots"
            )

    stale["net"]["bytes_sent_total"] = -999
    stale["cpu"]["percent"] = -1
    after = lm.live_metrics_snapshot()
    assert after["net"].get("bytes_sent_total") != -999
    assert after["cpu"].get("percent") != -1


def test_totals_stay_live_while_rates_are_suppressed(monkeypatch):
    """The docstring promised it; the code froze the whole section.

    A total is a reading, not a delta -- it needs no time base. Rates do,
    and those correctly stay as the previous sample's.
    """
    import arena.observability.live_metrics as lm

    first = lm.live_metrics_snapshot()
    if not first.get("net", {}).get("available"):
        import pytest

        pytest.skip("psutil not installed; no counters to re-read")

    # `>=` would be a weak assertion: a FROZEN total also satisfies it,
    # and sabotage proved it -- deleting the refresh left this test
    # green. So drive the counter to a known, larger value instead of
    # hoping the host generated traffic during the test.
    import types

    bumped = first["net"]["bytes_recv_total"] + 4096

    def fake_net_io():
        return types.SimpleNamespace(
            bytes_sent=first["net"]["bytes_sent_total"] + 2048,
            bytes_recv=bumped,
            packets_sent=0,
            packets_recv=0,
        )

    monkeypatch.setattr(lm.psutil, "net_io_counters", fake_net_io)
    stale = lm.live_metrics_snapshot()
    assert stale["stale"] is True
    assert stale["net"]["bytes_recv_total"] == bumped, (
        "the total was reused from the cache instead of being re-read"
    )
    # ...and the rate is explicitly the old one, not a recomputed spike.
    assert stale["net"]["bytes_recv_per_sec"] == first["net"]["bytes_recv_per_sec"]
    assert "totals are live" in stale["stale_reason"]


def test_stale_snapshot_deep_copies_nested_values(monkeypatch):
    """A copied section is not enough when it contains a mutable list.

    The existing shallow-copy fix protects ``snapshot["gpu"]`` itself but
    still shares ``gpu["devices"]`` with the cache. A dashboard consumer
    mutating one device record would therefore corrupt the next response.
    """
    import arena.observability.live_metrics as lm

    cached = {
        "ok": True,
        "timestamp": 1000.0,
        "stale": False,
        "gpu": {"available": True, "devices": [{"name": "card"}]},
        "net": {"available": False},
    }
    monkeypatch.setattr(lm.time, "time", lambda: 1000.001)
    monkeypatch.setattr(lm, "_HAS_PSUTIL", False)
    monkeypatch.setattr(
        lm,
        "_LAST_SAMPLE",
        {"timestamp": 1000.0, "snapshot": cached},
        raising=False,
    )

    stale = lm.live_metrics_snapshot()
    stale["gpu"]["devices"][0]["name"] = "mutated-by-caller"

    assert cached["gpu"]["devices"][0]["name"] == "card"


def test_fresh_snapshot_does_not_alias_the_cache(monkeypatch):
    """The first return must be isolated from the cache too.

    Deep-copying only the stale path leaves the fresh snapshot object itself
    stored in ``_LAST_SAMPLE``. A caller mutating that first response then
    poisons the next stale response.
    """
    import arena.observability.live_metrics as lm

    now = [1000.0]
    monkeypatch.setattr(lm.time, "time", lambda: now[0])
    monkeypatch.setattr(lm, "_HAS_PSUTIL", False)
    monkeypatch.setattr(lm, "_LAST_SAMPLE", {}, raising=False)
    monkeypatch.setattr(lm, "_collect_cpu", lambda: {"available": True, "percent": 1.0})
    monkeypatch.setattr(lm, "_collect_memory", lambda: {"available": False})
    monkeypatch.setattr(lm, "_collect_swap", lambda: {"available": False})
    monkeypatch.setattr(
        lm,
        "_collect_net",
        lambda _now, _dt: {"available": True, "bytes_sent_total": 1},
    )
    monkeypatch.setattr(lm, "_collect_disk", lambda _now, _dt: {"available": False})
    monkeypatch.setattr(
        lm,
        "_collect_gpu",
        lambda _now: {"available": True, "devices": [{"name": "card"}]},
    )

    fresh = lm.live_metrics_snapshot()
    fresh["gpu"]["devices"][0]["name"] = "mutated-by-caller"
    now[0] += 0.001
    stale = lm.live_metrics_snapshot()

    assert stale["gpu"]["devices"][0]["name"] == "card"


def test_refresh_totals_keeps_the_old_reading_when_the_counter_fails(
    monkeypatch,
):
    """A counter that cannot be read must not become a fabricated zero.

    On a byte counter, zero reads as "the interface reset" -- inventing
    that is the same crime as bug #58's invented gigabit.
    """
    import arena.observability.live_metrics as lm

    if not lm._HAS_PSUTIL:
        import pytest

        pytest.skip("psutil not installed")

    snapshot = {
        "net": {"available": True, "bytes_sent_total": 111, "bytes_recv_total": 222},
        "disk": {"available": True, "read_bytes_total": 333, "write_bytes_total": 444},
    }

    def boom(*args, **kwargs):
        raise OSError("counter unavailable")

    monkeypatch.setattr(lm.psutil, "net_io_counters", boom)
    monkeypatch.setattr(lm.psutil, "disk_io_counters", boom)
    lm._refresh_totals(snapshot)
    assert snapshot["net"]["bytes_sent_total"] == 111
    assert snapshot["disk"]["write_bytes_total"] == 444


def test_refresh_totals_leaves_unavailable_sections_alone():
    """No inventing fields for a section that reported itself absent."""
    import arena.observability.live_metrics as lm

    snapshot = {
        "net": {"available": False, "reason": "psutil not installed"},
        "disk": {"available": False, "reason": "no disk counters"},
    }
    lm._refresh_totals(snapshot)
    assert snapshot["net"] == {"available": False, "reason": "psutil not installed"}
    assert "read_bytes_total" not in snapshot["disk"]


def test_a_zero_interval_is_suppressed_not_divided_by(monkeypatch):
    """`0.0 < dt` let the single most degenerate interval through.

    Windows' `time.time()` ticks about every 15.6 ms, so two polls inside
    one tick give `dt == 0.0` EXACTLY -- and the whole Windows matrix in
    CI went red on it while every Linux and macOS cell passed. Zero is
    not "enough time has passed", it is no time at all, and it is the
    worst possible denominator for the rates bug #58 was about.

    The clock is driven here rather than raced, so this fails on every
    platform if the boundary regresses -- not only on the one with the
    coarse clock.
    """
    import arena.observability.live_metrics as lm

    monkeypatch.setattr(lm.time, "time", lambda: 1000.0)
    lm._LAST_SAMPLE.clear()
    first = lm.live_metrics_snapshot()
    assert first["stale"] is False
    second = lm.live_metrics_snapshot()
    assert second["stale"] is True, "dt == 0.0 must take the stale path"


def test_a_backwards_clock_is_not_a_valid_time_base(monkeypatch):
    """NTP steps, suspend/resume and VM snapshots move the wall clock back.

    A negative dt divided into a positive counter delta yields a negative
    rate, which a sparkline renders as a plunge that never happened.
    """
    import arena.observability.live_metrics as lm

    now = [1000.0]
    monkeypatch.setattr(lm.time, "time", lambda: now[0])
    lm._LAST_SAMPLE.clear()
    lm.live_metrics_snapshot()
    now[0] = 990.0
    stale = lm.live_metrics_snapshot()
    assert stale["stale"] is True
    assert "backwards" in stale["stale_reason"]


def test_a_real_interval_is_still_reported_fresh(monkeypatch):
    """Reverse sabotage: the widened guard must not freeze normal polling."""
    import arena.observability.live_metrics as lm

    now = [1000.0]
    monkeypatch.setattr(lm.time, "time", lambda: now[0])
    lm._LAST_SAMPLE.clear()
    lm.live_metrics_snapshot()
    now[0] = 1000.0 + lm._MIN_SAMPLE_INTERVAL + 0.01
    fresh = lm.live_metrics_snapshot()
    assert fresh["stale"] is False
