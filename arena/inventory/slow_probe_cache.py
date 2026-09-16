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

import json
import os
import tempfile
import threading
import time
from pathlib import Path
from typing import Any, Callable

# Long on purpose: the data is near-static, the scan is expensive, and a
# stale-but-instant answer beats a fresh one nobody waited for.
_TTL_SEC = 1800.0

_EMPTY: dict[str, dict[str, Any]] = {
    "python_venvs": {"available": False, "venvs": []},
    "git_repos": {"available": False, "repos": []},
}


def _cache_dir() -> Path:
    """Where the cached scans live, following the agent home."""
    home = os.environ.get("ARENA_AGENT_HOME")
    base = Path(home).expanduser() if home else Path(tempfile.gettempdir())
    return base / ".inventory-cache"


def _cache_path(name: str) -> Path:
    return _cache_dir() / f"{name}.json"


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
    path = _cache_path(name)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"at": time.time(), "result": result}),
                       encoding="utf-8")
        os.replace(tmp, path)
    except OSError:
        # A cache that cannot be written is a slow cache, not a broken
        # bridge: the probe still ran and the caller still gets its
        # answer this time round.
        pass


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
        with _refresh_lock:
            _refreshing.discard(name)


def _start_refresh(name: str, collector: Callable[[], dict]) -> None:
    """Spawn one refresh for `name`, if none is already running."""
    with _refresh_lock:
        if name in _refreshing:
            return
        _refreshing.add(name)
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


def reset_for_tests() -> None:
    """Drop stored state so a test starts from a known position."""
    with _refresh_lock:
        _refreshing.clear()
    for name in _EMPTY:
        try:
            _cache_path(name).unlink()
        except OSError:
            pass
