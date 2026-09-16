"""The two $HOME-crawling probes must not be collected inline (#385).

`python_venvs` and `git_repos` walk the home directory to depth 5. On
the reporting machine that is 31.6s and 15.7s -- together 54% of the
collection, and the reason `/v1/hardware` sat at 81s against a 90s
ceiling until the probes were parallelised (#386), then 43s after.

Measured on that Windows box with this change:

    collect #1 (cold): 18.3s  venvs=pending          repos=pending
    collect #2 (warm): 12.9s  venvs=ready n=15       repos=ready n=30

So the request stopped waiting for them, and the data still arrives --
which is the pair of properties these tests pin. A cache that returned
`pending` forever would satisfy "fast" while making the feature
useless, so every timing assertion here has a matching one on content.
"""
from __future__ import annotations

import threading
import time

import pytest

from arena.inventory import slow_probe_cache as spc


@pytest.fixture(autouse=True)
def _fresh_cache():
    """Each test starts with no cached result and none in flight."""
    spc.reset_for_tests()
    yield
    spc.reset_for_tests()


def _call_with_deadline(fn, seconds: float = 2.0):
    """Run `fn()` on a worker and fail rather than hang.

    An implementation that collects inline deadlocks -- `_refresh`
    wants the lock `get` already holds -- so a direct call would hang
    the suite instead of failing. Found by mutation: three tests here
    hung rather than reporting, which reads as "the mutation was not
    caught".
    """
    box: dict[str, object] = {}

    def run():
        box["value"] = fn()

    worker = threading.Thread(target=run, daemon=True)
    worker.start()
    worker.join(timeout=seconds)
    assert not worker.is_alive(), (
        f"the call was still running after {seconds}s -- it is collecting "
        "on the request path, or it deadlocked refreshing inline")
    return box["value"]


def _install(monkeypatch, name: str, fn) -> None:
    """Point one cache at `fn` instead of the real probe."""
    empty = ({"available": False, "venvs": []} if name == "python_venvs"
             else {"available": False, "repos": []})
    cache = spc._SlowProbeCache(name, fn, empty)
    monkeypatch.setattr(spc, "_caches", {name: cache})


def test_the_first_call_does_not_wait_for_the_scan(monkeypatch) -> None:
    """The defect itself: a 30-second crawl inside an HTTP request."""
    started = threading.Event()

    def slow_probe():
        started.set()
        time.sleep(5)
        return {"available": True, "venvs": [{"path": "/x"}]}

    _install(monkeypatch, "python_venvs", slow_probe)

    # Called on a worker thread with a deadline: an implementation that
    # collects inline does not merely return late, it can deadlock --
    # `_refresh` wants the lock `get` is already holding. A bare call
    # here would hang the whole suite instead of failing (found by
    # mutation), so the timeout is part of the assertion.
    box: dict[str, object] = {}

    def call():
        box["result"] = spc.cached_python_venvs()

    caller = threading.Thread(target=call, daemon=True)
    t0 = time.monotonic()
    caller.start()
    caller.join(timeout=2.0)
    elapsed = time.monotonic() - t0

    assert not caller.is_alive(), (
        "the call was still running after 2s -- the scan is on the request "
        "path, or it deadlocked trying to refresh inline")
    assert elapsed < 1.0, (
        f"the call blocked for {elapsed:.1f}s; the scan is still on the "
        "request path")
    result = box["result"]
    assert result["cache"] == {"state": "pending"}
    assert result["venvs"] == [], "pending must not invent data"
    assert started.wait(timeout=5), "the background scan never started"


def test_the_result_arrives_once_the_scan_finishes(monkeypatch) -> None:
    """The control: fast is worthless if the data never shows up.

    Without this, an implementation that returns `pending` forever and
    never runs the probe passes the test above.
    """
    _install(monkeypatch, "python_venvs",
             lambda: {"available": True, "venvs": [{"path": "/found"}]})

    _call_with_deadline(spc.cached_python_venvs)

    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        result = _call_with_deadline(spc.cached_python_venvs)
        if result["cache"]["state"] == "ready":
            break
        time.sleep(0.02)

    assert result["cache"]["state"] == "ready", "the scan never completed"
    assert result["venvs"] == [{"path": "/found"}]
    assert "age_sec" in result["cache"]


def test_concurrent_callers_start_exactly_one_scan(monkeypatch) -> None:
    """A refresh in flight must not spawn another.

    The dashboard refreshes every 15 seconds and the scan takes longer
    than that, so without the in-flight flag every refresh during a scan
    starts its own -- the pile-up this module exists to prevent.
    """
    runs = []
    lock = threading.Lock()

    def counted_probe():
        with lock:
            runs.append(1)
        time.sleep(0.4)
        return {"available": True, "venvs": []}

    _install(monkeypatch, "python_venvs", counted_probe)

    threads = [threading.Thread(target=spc.cached_python_venvs, daemon=True)
               for _ in range(12)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=5)

    assert all(not t.is_alive() for t in threads), (
        "a caller never returned -- the scan is inline, or it deadlocked")
    time.sleep(0.8)
    assert len(runs) == 1, (
        f"{len(runs)} scans started for 12 concurrent callers; the in-flight "
        "guard is not holding")


def test_a_raising_probe_becomes_an_error_not_a_hang(monkeypatch) -> None:
    """A probe that throws must not leave the cache refreshing forever.

    If the exception escaped `_refresh`, `_refreshing` would stay True
    and no later call would ever retry -- the section would read
    `pending` for the life of the process.
    """
    def boom():
        raise PermissionError("no access to $HOME")

    _install(monkeypatch, "python_venvs", boom)

    spc.cached_python_venvs()

    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        result = spc.cached_python_venvs()
        if result["cache"]["state"] == "ready":
            break
        time.sleep(0.02)

    assert result["cache"]["state"] == "ready", (
        "the cache is still pending, so the failed scan wedged it")
    assert result["error"] == "PermissionError: no access to $HOME"
    assert result["venvs"] == []


def test_a_stale_entry_is_served_while_it_refreshes(monkeypatch) -> None:
    """Stale-but-instant beats fresh-but-late for near-static data.

    A virtualenv that appeared five minutes ago is not news, and the
    alternative is making someone wait 30 seconds for the same answer.

    The property is "the stale read does not block and does not come
    back empty" -- deliberately *not* "it returns the old value". An
    earlier version asserted the latter and failed on macOS, where the
    background refresh finished before the assertion ran: a correct
    implementation, a racing test. Either value is fine here; an empty
    list or a blocked call is not.
    """
    started = threading.Event()
    release = threading.Event()

    def slow_second_scan():
        if started.is_set():
            release.wait(timeout=5)
            return {"available": True, "venvs": [{"path": "/second"}]}
        started.set()
        return {"available": True, "venvs": [{"path": "/first"}]}

    _install(monkeypatch, "python_venvs", slow_second_scan)
    monkeypatch.setattr(spc, "_TTL_SEC", 0.05)

    _call_with_deadline(spc.cached_python_venvs)
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        if _call_with_deadline(spc.cached_python_venvs)["cache"]["state"] == "ready":
            break
        time.sleep(0.02)

    time.sleep(0.1)                      # let the entry go stale
    t0 = time.monotonic()
    stale = _call_with_deadline(spc.cached_python_venvs)
    elapsed = time.monotonic() - t0
    release.set()

    assert elapsed < 1.0, "serving a stale entry blocked on the refresh"
    assert stale["cache"]["state"] == "ready", (
        "a stale entry was downgraded to pending; the previous result "
        "should keep being served while the refresh runs")
    assert stale["venvs"], (
        "the stale read returned an empty list instead of the last known "
        "result")


def test_the_registry_uses_the_cached_probes() -> None:
    """The wiring, checked rather than assumed.

    Everything above tests the cache in isolation; this is what makes it
    reach `/v1/hardware`. A registry still pointing at the raw
    collectors would leave the endpoint exactly as slow with every unit
    test green.
    """
    from arena.inventory.registry import REGISTRY

    by_name = {s.name: s for s in REGISTRY}

    assert by_name["python_venvs"].collector is spc.cached_python_venvs
    assert by_name["git_repos"].collector is spc.cached_git_repos
