"""Inventory probes run concurrently, without changing what they return (#385).

`/v1/hardware` collects 46 probes and took 81 seconds on the reporting
machine's Windows box -- against a 90-second ceiling, so it tipped over
under any extra load and the dashboard showed "Loading hardware
data..." forever. The probes are independent and spend nearly all their
time waiting on subprocesses, WMI and the filesystem, so the serial loop
was the whole problem.

Measured on that machine, same process, same probes:

    serial     79.0s  errors=9
    parallel   43.3s  errors=9
    only in parallel: []
    only in serial  : []

The error sets being identical is the part that matters: parallelism
must not change any probe's outcome, only when it runs.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Any

import pytest

from arena.inventory import report


@dataclass
class _Probe:
    """Stand-in for a registry section: a name and a callable."""

    name: str
    collector: Any


def test_probes_do_not_run_one_after_another(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """The defect itself: 46 sleeps in series cost the sum of them.

    Each fake probe sleeps 100ms. Serially that is 800ms; concurrently
    it is about one sleep. The threshold is deliberately loose -- this
    asserts "not serial", not a particular speed, so it does not become
    a timing flake on a loaded runner.
    """
    probes = [_Probe(f"p{i}", lambda: time.sleep(0.1) or {"ok": True})
              for i in range(8)]
    monkeypatch.setattr(report, "REGISTRY", probes)

    started = time.monotonic()
    result = report.collect()
    elapsed = time.monotonic() - started

    assert elapsed < 0.5, (
        f"8 probes of 100ms took {elapsed:.2f}s -- that is the serial sum, "
        "so they are not running concurrently")
    assert all(result[f"p{i}"] == {"ok": True} for i in range(8))


def test_every_probe_still_appears_in_the_result(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """Concurrency must not drop or reorder a section.

    `pool.map` preserves input order, but the guarantee worth pinning is
    that every registered name lands in the payload -- a result missing
    a key looks to the dashboard exactly like a probe that returned
    nothing.
    """
    probes = [_Probe(f"s{i}", lambda i=i: {"index": i}) for i in range(20)]
    monkeypatch.setattr(report, "REGISTRY", probes)

    result = report.collect()

    for i in range(20):
        assert result[f"s{i}"] == {"index": i}, f"s{i} missing or wrong"


def test_a_raising_probe_still_becomes_an_error_entry(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """The contract that predates this change: probes never crash the run.

    An exception raised inside a worker thread is easy to lose -- it
    would surface only when the future is read, and a `pool.map` that is
    never fully consumed would swallow it. The neighbours must still be
    collected.
    """
    def boom():
        raise RuntimeError("probe exploded")

    probes = [
        _Probe("before", lambda: {"ok": True}),
        _Probe("broken", boom),
        _Probe("after", lambda: {"ok": True}),
    ]
    monkeypatch.setattr(report, "REGISTRY", probes)

    result = report.collect()

    assert result["broken"] == {"error": "probe exploded"}
    assert result["before"] == {"ok": True}
    assert result["after"] == {"ok": True}


def test_probes_really_do_overlap(monkeypatch: pytest.MonkeyPatch) -> None:
    """Observed from inside the probes, not inferred from the clock.

    The timing test above can be satisfied by a fast machine running
    things serially. This one records how many probes are inside their
    collector at the same moment, so it fails on a serial
    implementation however quick the box is.
    """
    live = 0
    peak = 0
    lock = threading.Lock()

    def probe():
        nonlocal live, peak
        with lock:
            live += 1
            peak = max(peak, live)
        time.sleep(0.05)
        with lock:
            live -= 1
        return {"ok": True}

    monkeypatch.setattr(report, "REGISTRY",
                        [_Probe(f"c{i}", probe) for i in range(6)])

    report.collect()

    assert peak > 1, (
        f"peak concurrency was {peak}; the probes ran one at a time")


def test_a_single_section_skips_the_pool(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """`--section` asks for one probe; a pool would only add overhead.

    Also the control for the tests above: they would all pass on an
    implementation that pools unconditionally, and this pins the
    deliberate exception to it.
    """
    ran_in: list[str] = []

    def probe():
        ran_in.append(threading.current_thread().name)
        return {"ok": True}

    monkeypatch.setattr(report, "REGISTRY",
                        [_Probe("only", probe), _Probe("other", probe)])

    report.collect(only_section="only")

    assert ran_in == [threading.current_thread().name], (
        f"the single-section path used a worker thread ({ran_in}); it should "
        "run inline")
