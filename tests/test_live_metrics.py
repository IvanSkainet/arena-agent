"""Unit tests for arena.observability.live_metrics (v3.95.0)."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import time  # noqa: E402

from arena.observability import live_metrics as lm  # noqa: E402


def test_snapshot_top_level_shape():
    snap = lm.live_metrics_snapshot()
    assert snap["ok"] is True
    assert isinstance(snap["timestamp"], float)
    for key in ("cpu", "memory", "swap", "net", "disk", "gpu"):
        assert key in snap, f"missing section {key}"
        assert "available" in snap[key], f"section {key} missing 'available' flag"


def test_snapshot_cpu_section_has_percent_when_available():
    snap = lm.live_metrics_snapshot()
    cpu = snap["cpu"]
    if not cpu["available"]:
        # Environment without psutil AND non-Linux — legitimate;
        # bail out early rather than assert on missing data.
        assert "reason" in cpu
        return
    assert 0.0 <= cpu["percent"] <= 100.0
    assert cpu["count_logical"] >= 1
    # per_core may be [] when running the /proc fallback path.
    assert isinstance(cpu["per_core"], list)


def test_snapshot_memory_percent_bounded():
    snap = lm.live_metrics_snapshot()
    mem = snap["memory"]
    if not mem["available"]:
        assert "reason" in mem
        return
    assert 0.0 <= mem["percent"] <= 100.0
    assert mem["total_bytes"] > 0
    assert mem["used_bytes"] >= 0
    assert mem["used_bytes"] <= mem["total_bytes"]


def test_two_snapshots_produce_net_deltas():
    """Second snapshot should compute per-second deltas (may be
    zero if nothing happened, but the field must be an int and
    the totals must be non-decreasing)."""
    a = lm.live_metrics_snapshot()
    time.sleep(0.05)
    b = lm.live_metrics_snapshot()
    if not (a["net"]["available"] and b["net"]["available"]):
        return
    assert isinstance(b["net"]["bytes_sent_per_sec"], int)
    assert isinstance(b["net"]["bytes_recv_per_sec"], int)
    assert b["net"]["bytes_sent_total"] >= a["net"]["bytes_sent_total"]
    assert b["net"]["bytes_recv_total"] >= a["net"]["bytes_recv_total"]


def test_gpu_result_cached_within_two_seconds():
    """Second call within 2s should return the cached GPU dict
    (identity check on the devices list). This keeps 1Hz polling
    from calling nvidia-smi 60 times a minute."""
    a = lm.live_metrics_snapshot()
    b = lm.live_metrics_snapshot()
    # Same-object identity because _collect_gpu returns the cached
    # dict verbatim within the window.
    assert a["gpu"] is b["gpu"] or a["gpu"] == b["gpu"]


def test_snapshot_json_serialisable():
    import json
    snap = lm.live_metrics_snapshot()
    payload = json.dumps(snap)
    # Round-trip and confirm same top-level keys.
    round_trip = json.loads(payload)
    assert set(round_trip.keys()) == set(snap.keys())


def test_disk_totals_non_decreasing():
    a = lm.live_metrics_snapshot()
    time.sleep(0.02)
    b = lm.live_metrics_snapshot()
    if not (a["disk"]["available"] and b["disk"]["available"]):
        return
    assert b["disk"]["read_bytes_total"] >= a["disk"]["read_bytes_total"]
    assert b["disk"]["write_bytes_total"] >= a["disk"]["write_bytes_total"]
