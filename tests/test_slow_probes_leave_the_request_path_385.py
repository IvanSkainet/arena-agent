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

import itertools
import json
import os
import threading
import time
from pathlib import Path

import pytest

from arena.inventory import slow_probe_cache as spc

REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def _fresh_cache(tmp_path, monkeypatch):
    """Each test gets its own cache directory and no in-flight state.

    `ARENA_AGENT_HOME` is redirected at a tmpdir: without it every test
    -- and every parallel pytest process -- shares one directory under
    the system temp, so one test's refresh overwrites another's stored
    entry. That is what made three of these fail intermittently under
    parallel runs, and it took a while to see because each individual
    fix looked plausible.
    """
    monkeypatch.setenv("ARENA_AGENT_HOME", str(tmp_path))
    spc.reset_for_tests()
    yield
    spc.reset_for_tests()


def _wait_for_result(call, timeout: float = 30.0) -> dict:
    """Block until the cache reports `ready`, then return it.

    Polling with a short fixed budget was wrong twice over: on a loaded
    runner the scan outlives the budget (two tests failed that way under
    four parallel pytest processes), and waiting on the in-flight flag
    alone races the thread that has not started yet. Waiting for the
    observable outcome avoids both, with a budget long enough that only
    a genuinely stuck refresh hits it.
    """
    deadline = time.monotonic() + timeout
    result = call()
    while time.monotonic() < deadline:
        if result["cache"]["state"] == "ready":
            return result
        time.sleep(0.01)
        result = call()
    return result


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


_counter = itertools.count()
_installed_names: dict[object, str] = {}


def _mine_in_flight(call) -> bool:
    """Is a refresh running for the entry `call` reads?"""
    with spc._refresh_lock:
        return _installed_names[call] in spc._refreshing


def _install(monkeypatch, name: str, fn):
    """A caller reading an isolated cache entry backed by `fn`.

    Each call gets a unique name: `_refreshing` is keyed by name and
    shared across the process, so two tests using "python_venvs" gate
    each other's refreshes -- which is how three of these failed under
    four parallel pytest processes.
    """
    unique = f"{name}_t{next(_counter)}"
    spc.register_for_tests(unique)
    caller = lambda: spc._cached(unique, fn)  # noqa: E731
    _installed_names[caller] = unique
    return caller


def test_the_first_call_does_not_wait_for_the_scan(monkeypatch) -> None:
    """The defect itself: a 30-second crawl inside an HTTP request."""
    started = threading.Event()
    finish = threading.Event()

    def slow_probe():
        started.set()
        # Released at the end of the test rather than a fixed sleep: a
        # scan still running when the fixture tears down trips its
        # "refreshes still in flight" guard, which is the guard doing
        # its job.
        finish.wait(timeout=30)
        return {"available": True, "venvs": [{"path": "/x"}]}

    call_cached = _install(monkeypatch, "python_venvs", slow_probe)

    # Called on a worker thread with a deadline: an implementation that
    # collects inline does not merely return late, it can deadlock --
    # `_refresh` wants the lock `get` is already holding. A bare call
    # here would hang the whole suite instead of failing (found by
    # mutation), so the timeout is part of the assertion.
    box: dict[str, object] = {}

    def call():
        box["result"] = call_cached()

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
    assert started.wait(timeout=10), "the background scan never started"
    finish.set()


def test_the_result_arrives_once_the_scan_finishes(monkeypatch) -> None:
    """The control: fast is worthless if the data never shows up.

    Without this, an implementation that returns `pending` forever and
    never runs the probe passes the test above.
    """
    call_cached = _install(
        monkeypatch, "python_venvs",
        lambda: {"available": True, "venvs": [{"path": "/found"}]})

    _call_with_deadline(call_cached)
    result = _wait_for_result(call_cached)

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

    call_cached = _install(monkeypatch, "python_venvs", counted_probe)

    threads = [threading.Thread(target=call_cached, daemon=True)
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

    call_cached = _install(monkeypatch, "python_venvs", boom)

    _call_with_deadline(call_cached)
    result = _wait_for_result(call_cached)

    assert result["cache"]["state"] == "ready", (
        "the cache is still pending, so the failed scan wedged it")
    assert result["error"] == "PermissionError: no access to $HOME"
    assert result["venvs"] == []


def test_a_stale_entry_is_served_while_it_refreshes(monkeypatch) -> None:
    """Stale-but-instant beats fresh-but-late for near-static data.

    A virtualenv that appeared five minutes ago is not news, and the
    alternative is making someone wait 30 seconds for the same answer.

    The stored entry is written directly rather than produced by a
    background scan. Three earlier versions of this test tried to race
    a real refresh -- by sleeping, by a zero TTL, by waiting on the
    in-flight flag -- and each one failed intermittently under parallel
    runs. The behaviour under test is "what does a read do when the
    stored entry is old", which needs no concurrency at all.
    """
    name = f"python_venvs_stale{next(_counter)}"
    spc.register_for_tests(name)
    spc._write(name, {"available": True, "venvs": [{"path": "/stored"}]})
    monkeypatch.setattr(spc, "_TTL_SEC", 0.0)      # the entry is now stale

    scanned = threading.Event()
    result = _call_with_deadline(
        lambda: spc._cached(name, lambda: (scanned.set(), {"venvs": []})[1]))

    assert result["cache"]["state"] == "ready", (
        "a stale entry was downgraded to pending; the previous result "
        "should keep being served while the refresh runs")
    assert result["venvs"] == [{"path": "/stored"}], (
        "the stale read should serve the stored result, not an empty one")
    assert scanned.wait(timeout=10), (
        "a stale read must also kick off a refresh")


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


def test_the_cache_survives_the_process_that_filled_it(tmp_path) -> None:
    """The P0 this design was rebuilt around.

    `/v1/hardware` does not call these collectors in-process: it runs
    `scripts/inventory.py` as a subprocess (`arena/inventory/runner.py`).
    The first version kept the cache in module state with a daemon
    refresh thread, so both died with that CLI -- three consecutive runs
    all returned `pending` and no request ever saw a result. Caught in
    review; my own benchmark had missed it because it called `collect()`
    in one process.

    So the state has to outlive the process that produced it, and this
    is the test that would have caught it: fill the cache in one
    interpreter, read it back in another.
    """
    import subprocess
    import sys

    env = dict(os.environ, ARENA_AGENT_HOME=str(tmp_path))
    fill = (
        "import sys; sys.path.insert(0, %r)\n"
        "from arena.inventory import slow_probe_cache as spc\n"
        "spc._cached('python_venvs', lambda: "
        "{'available': True, 'venvs': [{'path': '/from-first-process'}]})\n"
    ) % str(REPO_ROOT)
    subprocess.run([sys.executable, "-c", fill], env=env, timeout=60,
                   capture_output=True, text=True, check=True)

    read = (
        "import json, sys; sys.path.insert(0, %r)\n"
        "from arena.inventory import slow_probe_cache as spc\n"
        "print(json.dumps(spc._cached('python_venvs', lambda: "
        "{'available': False, 'venvs': []})))\n"
    ) % str(REPO_ROOT)
    out = subprocess.run([sys.executable, "-c", read], env=env, timeout=60,
                         capture_output=True, text=True, check=True)

    result = json.loads(out.stdout)
    assert result["cache"]["state"] == "ready", (
        "a second process saw `pending`; the cache does not survive the "
        "inventory subprocess, so /v1/hardware would never get a result")
    assert result["venvs"] == [{"path": "/from-first-process"}]


def test_a_probe_that_kills_the_worker_does_not_wedge_the_cache(
        monkeypatch) -> None:
    """An unexpected failure must not stop every later refresh.

    `_refreshing` gates new scans. If it is cleared only on the normal
    path, anything escaping before that -- a BaseException, a failure
    inside the write -- leaves it set and the cache returns `pending`
    for the life of the process, never retrying. Hence the `finally`.

    `KeyboardInterrupt` is used deliberately: it is a BaseException, so
    it slips past the `except Exception` that handles ordinary probe
    errors and exercises the path a bare `except` would not.
    """
    died = threading.Event()

    def hostile():
        died.set()
        raise KeyboardInterrupt("worker killed")

    call_cached = _install(monkeypatch, "python_venvs", hostile)
    _call_with_deadline(call_cached)
    assert died.wait(timeout=10), "the hostile probe never ran"

    # The flag is cleared in the worker's `finally`, which runs after
    # the probe raises; wait for that rather than guessing a duration.
    # Only this test's own entry: `_refreshing` is process-wide and a
    # parallel test's scan being in flight says nothing about ours.
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline and _mine_in_flight(call_cached):
        time.sleep(0.01)
    assert not _mine_in_flight(call_cached), (
        "the in-flight flag survived a worker that died, so no later "
        "refresh can ever start")

    ran = threading.Event()
    retry = _install(monkeypatch, "python_venvs",
                     lambda: (ran.set(), {"available": True, "venvs": []})[1])
    _call_with_deadline(retry)

    assert ran.wait(timeout=10), (
        "the cache never retried after the failed refresh")


def test_concurrent_processes_run_the_probe_once(tmp_path) -> None:
    """Single-flight has to hold across processes, not just threads.

    `_refreshing` is per-interpreter, and `/v1/hardware` spawns a fresh
    `scripts/inventory.py` for every request -- so three overlapping
    requests each ran the same 30-second scan (measured: 3 executions
    from 3 processes). A claim file is what the other processes can
    see.
    """
    import subprocess
    import sys

    env = dict(os.environ, ARENA_AGENT_HOME=str(tmp_path))
    code = (
        "import sys, time, os, pathlib\n"
        "sys.path.insert(0, %r)\n"
        "from arena.inventory import slow_probe_cache as spc\n"
        "mark = pathlib.Path(%r) / ('ran-%%d' %% os.getpid())\n"
        "def probe():\n"
        "    mark.write_text('x')\n"
        "    time.sleep(2)\n"
        "    return {'available': True, 'venvs': []}\n"
        "spc._cached('python_venvs', probe)\n"
    ) % (str(REPO_ROOT), str(tmp_path))

    procs = [subprocess.Popen([sys.executable, "-c", code], env=env)
             for _ in range(3)]
    for proc in procs:
        proc.wait(timeout=90)

    ran = list(tmp_path.glob("ran-*"))
    assert len(ran) == 1, (
        f"{len(ran)} processes ran the scan; the claim file is not holding "
        "single-flight across processes")


def test_an_abandoned_claim_does_not_block_refreshes_forever(
        monkeypatch, tmp_path) -> None:
    """A process killed mid-scan must not wedge the cache permanently.

    The control for the test above: a claim that is never released
    would make single-flight into never-flight, which is worse than
    scanning twice.
    """
    name = f"python_venvs_claim{next(_counter)}"
    spc.register_for_tests(name)

    claim = spc._cache_path(name).with_suffix(".claim")
    claim.parent.mkdir(parents=True, exist_ok=True)
    claim.write_text("")
    old = time.time() - (spc._CLAIM_STALE_SEC + 60)
    os.utime(claim, (old, old))

    assert not spc._claim(name), "a fresh claim should be refused once held"
    # The refusal above reclaims it, so the next attempt succeeds.
    assert spc._claim(name), (
        "a stale claim was never reclaimed; one killed process would block "
        "every future refresh")


def test_the_cache_directory_is_not_world_readable(tmp_path) -> None:
    """The payload maps every venv and checkout under $HOME.

    That is a description of the user's work, and the default umask
    would leave it readable by other local users (review).
    """
    if os.name != "posix":
        pytest.skip("POSIX permission bits")

    name = f"python_venvs_perm{next(_counter)}"
    spc.register_for_tests(name)
    spc._write(name, {"available": True, "venvs": [{"path": "/x"}]})

    path = spc._cache_path(name)
    assert path.stat().st_mode & 0o077 == 0, (
        f"{path} is readable by other users: {oct(path.stat().st_mode)}")
    assert path.parent.stat().st_mode & 0o077 == 0, (
        f"{path.parent} is readable by other users")


def test_a_failed_write_leaves_no_staging_file() -> None:
    """Repeated background failures must not litter the cache directory.

    The failure is provoked with an unserialisable payload rather than
    by patching `os.replace`: patching a module's `os` is a global
    patch, which the repository ratchets against, and it would reach
    every other user of that module for the duration of the test.
    """
    name = f"python_venvs_litter{next(_counter)}"
    spc.register_for_tests(name)
    spc._cache_path(name).parent.mkdir(parents=True, exist_ok=True)

    class Unserialisable:
        pass

    with pytest.raises(TypeError):
        spc._write_atomically(spc._cache_path(name),
                              {"venvs": Unserialisable()})

    leftovers = list(spc._cache_path(name).parent.glob("*.tmp"))
    assert leftovers == [], f"staging files left behind: {leftovers}"
