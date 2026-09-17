"""Keep the two filesystem-crawling probes off the request path (#385).

`python_venvs` and `git_repos` walk `$HOME` to depth 5. On the reporting
machine that is 31.6s and 15.7s -- 54% of a collection, and the reason
`/v1/hardware` sat at 81s against a 90s ceiling.

Neither answer changes minute to minute, so the request never waits for
a scan: it serves the last result from disk and refreshes in the
background when that goes stale.

**On disk, not in memory.** `/v1/hardware` runs `scripts/inventory.py`
as a *subprocess* (`arena/inventory/runner.py`), so a process-local
cache and its daemon refresh thread die with that CLI -- every request
would see a fresh `pending` forever. Caught in review; verified by
running the CLI three times and getting `pending` each time. The state
therefore lives in a file under `ARENA_AGENT_HOME`, which the next
subprocess can read.

The payload keeps the shape callers already expect -- `available`, plus
`venvs`/`repos` -- so a consumer that ignores the new `cache` key sees
an empty list before the first scan finishes rather than a different
schema.
"""
from __future__ import annotations

import contextlib
import json
import logging
import os
import tempfile
import threading
import time
from pathlib import Path
from typing import Any, Callable

# Long on purpose: the data is near-static, the scan is expensive, and a
# stale-but-instant answer beats a fresh one nobody waited for.
_TTL_SEC = 1800.0

_LOG = logging.getLogger(__name__)

# Owner-only: the cached scans list every virtualenv and git checkout
# under $HOME, which is a map of the user's work (review).
_DIR_MODE = 0o700
_FILE_MODE = 0o600

_EMPTY: dict[str, dict[str, Any]] = {
    "python_venvs": {"available": False, "venvs": []},
    "git_repos": {"available": False, "repos": []},
}


def _cache_dir() -> Path:
    """Where the cached scans live, following the agent home.

    Falls back to the user's home rather than the shared temp
    directory: the payload maps every virtualenv and checkout under
    $HOME, and `/tmp/.inventory-cache` would both mix installations and
    expose that to other local users (review).
    """
    home = os.environ.get("ARENA_AGENT_HOME")
    base = Path(home).expanduser() if home else Path.home() / ".arena"
    return base / ".inventory-cache"


# The only names this module ever caches. `_cache_path` indexes this
# map rather than interpolating its argument: the value is internal, not
# user input, but a path built by formatting a string is a path traversal
# to any scanner reading the code -- and they are right that nothing
# here guarantees it (SonarCloud S6549, BLOCKER).
_FILENAMES = {
    "python_venvs": "python_venvs.json",
    "git_repos": "git_repos.json",
}


def register_for_tests(name: str) -> None:
    """Add an isolated cache name, so tests do not share in-flight state.

    `_refreshing` is keyed by name and process-wide. Two tests both
    using "python_venvs" gate each other: the second sees the first's
    refresh in flight and skips its own, then asserts on a result that
    never came. Each test registers its own name instead.
    """
    if not name.replace("_", "").replace("-", "").isalnum():
        raise ValueError(f"unsafe cache name: {name!r}")
    _FILENAMES.setdefault(name, f"{name}.json")
    _EMPTY.setdefault(name, {"available": False, "venvs": []})


def _cache_path(name: str) -> Path:
    return _cache_dir() / _FILENAMES[name]


def _read(name: str) -> tuple[dict[str, Any] | None, float]:
    """The stored result and its age, or `(None, 0)` if unusable."""
    try:
        raw = json.loads(_cache_path(name).read_text(encoding="utf-8"))
        return raw["result"], max(0.0, time.time() - float(raw["at"]))
    except (OSError, ValueError, KeyError, TypeError):
        # Missing, truncated by a crash mid-write, or written by an
        # older shape: treated as absent rather than fatal. The probe
        # runs again and overwrites it.
        return None, 0.0


def _write(name: str, result: dict[str, Any]) -> None:
    """Store `result` atomically, so a reader never sees half a file."""
    try:
        _write_atomically(_cache_path(name), result)
    except OSError as exc:
        # A cache that cannot be written is a slow cache, not a broken
        # bridge: the probe still ran and the caller still gets its
        # answer this time round. Logged rather than swallowed, because
        # a permanently unwritable cache means every request re-runs a
        # 30-second scan and nothing says why (review).
        _LOG.warning("inventory cache write failed for %s: %s", name, exc)


def _write_atomically(path: Path, result: dict[str, Any]) -> None:
    """Stage to a unique temp file, then rename it into place.

    `path.with_suffix(".tmp")` gave every writer the same staging name,
    so two concurrent refreshes clobbered each other's partial file and
    `os.replace` could publish a truncated one -- which a reader then
    discards, reporting `pending` even though a scan had just finished.
    Seen once in six parallel test runs.
    """
    path.parent.mkdir(parents=True, exist_ok=True, mode=_DIR_MODE)
    fd, tmp_name = tempfile.mkstemp(dir=str(path.parent),
                                    prefix=path.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump({"at": time.time(), "result": result}, fh)
        os.chmod(tmp_name, _FILE_MODE)
        os.replace(tmp_name, path)
    except BaseException:
        # Otherwise a failing write leaves its unique staging file
        # behind, and repeated background failures litter the cache
        # directory (review).
        with contextlib.suppress(OSError):
            os.unlink(tmp_name)
        raise


_refreshing: set[str] = set()
_refresh_lock = threading.Lock()


def _refresh(name: str, collector: Callable[[], dict]) -> None:
    """Run the probe and store the result. Never raises."""
    try:
        try:
            result = collector()
        except Exception as exc:  # noqa: BLE001 -- probes never crash the run
            previous, _ = _read(name)
            # A failed refresh must not throw away a good answer
            # (review): keep the last one and attach the error.
            result = dict(previous) if previous else dict(_EMPTY[name])
            result["error"] = f"{type(exc).__name__}: {exc}"
            result["error_type"] = type(exc).__name__
        _write(name, result)
    finally:
        # In a `finally` so an unexpected failure cannot wedge the cache
        # into "refreshing" forever, which would stop every later
        # refresh from starting (review).
        _release(name)
        with _refresh_lock:
            _refreshing.discard(name)


# How long a claim file is trusted before it is treated as abandoned.
# Longer than any real scan (the worst measured is ~32s) and shorter
# than the TTL, so a process killed mid-scan cannot wedge refreshes for
# the rest of the day.
_CLAIM_STALE_SEC = 300.0


def _claim(name: str) -> bool:
    """Take the cross-process right to refresh `name`.

    `_refreshing` only covers one interpreter, and `/v1/hardware` runs
    `scripts/inventory.py` as a *fresh subprocess* per request -- so
    three concurrent requests ran the same 30-second scan three times
    (measured, review). An exclusive-create file is the claim, since
    every process can see it.

    A stale claim is reclaimed: a process killed mid-scan would
    otherwise block every future refresh, which is worse than
    occasionally scanning twice.
    """
    claim = _cache_path(name).with_suffix(".claim")
    try:
        claim.parent.mkdir(parents=True, exist_ok=True, mode=_DIR_MODE)
        fd = os.open(str(claim), os.O_CREAT | os.O_EXCL | os.O_WRONLY,
                     _FILE_MODE)
        os.close(fd)
        return True
    except FileExistsError:
        try:
            if time.time() - claim.stat().st_mtime > _CLAIM_STALE_SEC:
                claim.unlink(missing_ok=True)
                _LOG.warning("reclaimed a stale inventory scan lock for %s",
                             name)
        except OSError as exc:
            # Not fatal -- the caller simply does not refresh this time
            # -- but silence here means a claim nobody can stat or
            # unlink blocks every future refresh with no explanation
            # (review).
            _LOG.warning("could not inspect the inventory scan lock for "
                         "%s: %s", name, exc)
        return False
    except OSError as exc:
        # No claim file means no cross-process guard, but refusing to
        # scan at all would be worse: fall back to scanning.
        _LOG.warning("could not claim the inventory scan for %s: %s",
                     name, exc)
        return True


def _release(name: str) -> None:
    """Drop the cross-process claim, if this process holds one."""
    with contextlib.suppress(OSError):
        _cache_path(name).with_suffix(".claim").unlink(missing_ok=True)


def _start_refresh(name: str, collector: Callable[[], dict]) -> None:
    """Spawn one refresh for `name`, if none is already running."""
    with _refresh_lock:
        if name in _refreshing:
            return
        _refreshing.add(name)
    if not _claim(name):
        # Another process is already scanning; its result lands in the
        # shared file and this one will read it.
        with _refresh_lock:
            _refreshing.discard(name)
        return
    try:
        # Not a daemon. `scripts/inventory.py` is a short-lived CLI --
        # `/v1/hardware` runs it as a subprocess -- and a daemon thread
        # is killed at interpreter exit, so the scan never finished and
        # the file was never written: three consecutive runs all
        # returned `pending` (review). A non-daemon thread keeps the
        # process alive until the scan lands, which is the point.
        threading.Thread(target=_refresh, args=(name, collector),
                         name=f"slowprobe-{name}", daemon=False).start()
    except RuntimeError:
        # Thread creation can fail during interpreter shutdown. Clear
        # the flag so a later call retries instead of seeing a refresh
        # that never started (review).
        with _refresh_lock:
            _refreshing.discard(name)
        # And the claim file, which `_refresh`'s `finally` would have
        # released had the worker ever reached it. Without this the
        # cross-process guard stays held for the full stale window --
        # five minutes in which no process will refresh, because every
        # one of them sees a claim owned by nobody (review).
        _release(name)
        raise


def _cached(name: str, collector: Callable[[], dict]) -> dict[str, Any]:
    """The last stored result, never blocking on a scan."""
    result, age = _read(name)
    if result is None or age > _TTL_SEC:
        _start_refresh(name, collector)
    if result is None:
        pending = dict(_EMPTY[name])
        pending["cache"] = {"state": "pending"}
        return pending
    out = dict(result)
    out["cache"] = {"state": "ready", "age_sec": round(age, 1)}
    return out


def cached_python_venvs() -> dict[str, Any]:
    """`get_python_venvs` without the 31-second wait."""
    from arena.inventory.probe_agent_ctx import get_python_venvs

    return _cached("python_venvs", get_python_venvs)


def cached_git_repos() -> dict[str, Any]:
    """`get_git_repos` without the 15-second wait."""
    from arena.inventory.probe_agent_ctx import get_git_repos

    return _cached("git_repos", get_git_repos)


def reset_for_tests(timeout: float = 5.0) -> None:
    """Drop stored state so a test starts from a known position.

    Waits for any refresh still in flight before clearing. Without
    that, a scan started by the previous test finishes mid-next-test
    and writes its result into the file the new one is reading -- which
    is exactly how `test_the_result_arrives_once_the_scan_finishes`
    failed on macOS with the *previous* test's value.
    """
    _await_quiet_refreshes(timeout)
    with _refresh_lock:
        _refreshing.clear()
    _delete_stored_results()


def _await_quiet_refreshes(timeout: float) -> None:
    """Wait for in-flight refreshes, or fail.

    Returning quietly on timeout let `reset_for_tests` clear the files
    while a scan was still running, so a late write reintroduced the
    cross-test race this is meant to prevent (review).
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with _refresh_lock:
            if not _refreshing:
                return
        time.sleep(0.01)
    # Snapshot under the lock: building this message from the live set
    # can read it mid-mutation, which either reports a misleading set or
    # raises "Set changed size during iteration" *from the failure
    # path* -- turning a clear diagnostic into a confusing one (review).
    with _refresh_lock:
        still = sorted(_refreshing)
    raise AssertionError(
        f"refreshes still in flight after {timeout}s: {still}")


def _delete_stored_results() -> None:
    """Remove every cached file, ignoring ones already gone."""
    for name in _FILENAMES:
        _release(name)
        try:
            _cache_path(name).unlink()
        except FileNotFoundError:
            # Already gone is the expected case, not a problem.
            pass
        except OSError as exc:
            # Anything else means the next test may read stale state,
            # which is the failure this helper exists to prevent
            # (review) -- so it is surfaced, not hidden.
            raise AssertionError(
                f"could not clear the cached {name}: {exc}") from exc
