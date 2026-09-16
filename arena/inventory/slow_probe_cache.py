"""Keep the two filesystem-crawling probes off the request path (#385).

`python_venvs` and `git_repos` walk `$HOME` to depth 5. On the reporting
machine that is 31.6s and 15.7s -- 54% of a 47-second collection, and
the reason `/v1/hardware` used to sit at 81s against a 90s ceiling.

Neither answer changes minute to minute: a virtualenv or a checkout that
appeared five minutes ago is not news. So the request never waits for
them. The first call returns `pending` and starts a background refresh;
every later call returns the last completed result with its age
attached, refreshing behind the scenes once it goes stale.

The payload keeps the shape callers already expect -- `available`,
plus `venvs`/`repos` -- so a consumer that ignores the new `cache` key
sees an empty list before the first scan finishes rather than a
different schema.
"""
from __future__ import annotations

import threading
import time
from typing import Any, Callable

# Long on purpose. The data is near-static, the scan is expensive, and
# a stale-but-instant answer beats a fresh one nobody waited for.
_TTL_SEC = 1800.0


class _SlowProbeCache:
    """One cached probe result, refreshed off the request path."""

    def __init__(self, name: str, collector: Callable[[], dict],
                 empty: dict[str, Any]) -> None:
        self._name = name
        self._collector = collector
        self._empty = empty
        self._lock = threading.Lock()
        self._result: dict[str, Any] | None = None
        self._at = 0.0
        self._refreshing = False

    def _refresh(self) -> None:
        try:
            result = self._collector()
        except Exception as exc:  # noqa: BLE001 -- probes never crash the run
            result = dict(self._empty)
            result["error"] = f"{type(exc).__name__}: {exc}"
        with self._lock:
            self._result = result
            self._at = time.monotonic()
            self._refreshing = False

    def _start_refresh_locked(self) -> None:
        """Spawn one refresh; callers already hold `self._lock`.

        The flag matters: without it every request during a 30-second
        scan starts another one, which is the pile-up this module
        exists to prevent.
        """
        if self._refreshing:
            return
        self._refreshing = True
        threading.Thread(target=self._refresh, name=f"slowprobe-{self._name}",
                         daemon=True).start()

    def get(self) -> dict[str, Any]:
        """The cached result, never blocking on a scan."""
        with self._lock:
            result = self._result
            age = time.monotonic() - self._at
            if result is None or age > _TTL_SEC:
                self._start_refresh_locked()
            if result is None:
                pending = dict(self._empty)
                pending["cache"] = {"state": "pending"}
                return pending
            out = dict(result)
            out["cache"] = {"state": "ready", "age_sec": round(age, 1)}
            return out


def _build() -> dict[str, _SlowProbeCache]:
    # Imported here rather than at module scope: probe_agent_ctx is a
    # heavier import than this module needs at definition time, and the
    # registry imports both.
    from arena.inventory.probe_agent_ctx import get_git_repos, get_python_venvs

    return {
        "python_venvs": _SlowProbeCache(
            "python_venvs", get_python_venvs,
            {"available": False, "venvs": []}),
        "git_repos": _SlowProbeCache(
            "git_repos", get_git_repos,
            {"available": False, "repos": []}),
    }


_caches: dict[str, _SlowProbeCache] | None = None
_caches_lock = threading.Lock()


def _cache_for(name: str) -> _SlowProbeCache:
    global _caches
    with _caches_lock:
        if _caches is None:
            _caches = _build()
        return _caches[name]


def cached_python_venvs() -> dict[str, Any]:
    """`get_python_venvs` without the 31-second wait."""
    return _cache_for("python_venvs").get()


def cached_git_repos() -> dict[str, Any]:
    """`get_git_repos` without the 15-second wait."""
    return _cache_for("git_repos").get()


def reset_for_tests() -> None:
    """Drop the caches so a test starts from a known state."""
    global _caches
    with _caches_lock:
        _caches = None
