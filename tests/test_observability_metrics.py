"""Observability metrics helper tests."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import arena.observability.metrics as m  # noqa: E402
import unified_bridge as ub  # noqa: E402


def test_metrics_reexported():
    assert ub.BRIDGE_METRICS is m.BRIDGE_METRICS
    assert ub._record_request is m._record_request
    assert ub._metrics_lock is m._metrics_lock


def test_record_request_updates_metrics():
    before = m.BRIDGE_METRICS["total_requests"]
    m.record_request(duration=0.001)
    assert m.BRIDGE_METRICS["total_requests"] == before + 1
    assert m.BRIDGE_METRICS["request_durations"][-1] == 0.001
