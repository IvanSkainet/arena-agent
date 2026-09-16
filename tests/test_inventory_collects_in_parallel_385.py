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

    The type is carried alongside the message: `str(e)` alone renders
    `FileNotFoundError("x")` and `PermissionError("x")` identically,
    and those call for different responses (review).
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

    assert result["broken"] == {"error": "RuntimeError: probe exploded",
                                "error_type": "RuntimeError"}
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


def test_two_collections_do_not_overlap(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """A cancelled request leaves its probes running; the next must wait.

    `asyncio.wait_for` abandons the executor task but cannot reach into
    the pool -- measured, four probes were still running 0.3s after the
    request gave up (review). The dashboard refreshes every 15s, so
    without a guard abandoned collections stack up indefinitely.

    Counted from inside the probes: if two collections overlap, probes
    from both are in flight at once and the count exceeds one
    collection's worth. An earlier version of this test only checked
    that neither thread deadlocked, which passed with the guard removed
    -- it asserted nothing.
    """
    live = 0
    peak = 0
    lock = threading.Lock()

    def probe():
        nonlocal live, peak
        with lock:
            live += 1
            peak = max(peak, live)
        time.sleep(0.08)
        with lock:
            live -= 1
        return {"ok": True}

    probes = [_Probe(f"g{i}", probe) for i in range(4)]
    monkeypatch.setattr(report, "REGISTRY", probes)

    threads = [threading.Thread(target=report.collect) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)

    assert all(not t.is_alive() for t in threads), "a collection deadlocked"
    assert peak <= len(probes), (
        f"{peak} probes were in flight at once but one collection only has "
        f"{len(probes)}; two collections overlapped, so abandoned work from "
        "a timed-out request can stack up")


def test_the_guard_does_not_serialise_probes_within_one_collection(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """The control: the lock is per collection, not per probe.

    A lock taken inside `_run_probe` would satisfy the test above while
    undoing the entire point of this change, so the overlap check is
    repeated here with the guard in place.
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
                        [_Probe(f"h{i}", probe) for i in range(6)])

    report.collect()

    assert peak > 1, (
        f"peak concurrency was {peak}; the in-flight guard is serialising "
        "individual probes instead of whole collections")
