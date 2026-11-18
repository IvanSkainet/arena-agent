"""Persist slow home scans without keeping the inventory CLI alive (T73).

A request subprocess reads the last result and starts an independent worker.
The worker owns a kernel lease while collecting; no daemon thread is lost on
CLI exit and no non-daemon thread delays its caller's subprocess.run().
"""
from __future__ import annotations

import json
import logging
import math
import os
import subprocess  # nosec B404 -- isolated fixed Python worker, argv only, never a shell
import sys
import tempfile
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from arena.home import agent_home
from arena.inventory.cache_lease import cache_lease

_TTL_SEC = 1800.0
_MAX_CACHE_BYTES = 8 * 1024 * 1024
_KEYS = {"python_venvs": "venvs", "git_repos": "repos"}
_LOG = logging.getLogger(__name__)
_WORKERS: list[subprocess.Popen] = []


def _cache_dir() -> Path:
    return agent_home() / ".inventory-cache"


def _path(name: str, directory: Path) -> Path:
    if name not in _KEYS:
        raise ValueError(f"unknown slow inventory probe: {name}")
    return directory / (name + ".json")


def _read(name: str, directory: Path) -> tuple[dict | None, float]:
    path = _path(name, directory)
    try:
        with path.open("rb") as stream:
            data = stream.read(_MAX_CACHE_BYTES + 1)
        if len(data) > _MAX_CACHE_BYTES:
            return None, 0.0
        raw = json.loads(data)
        result, at = raw["result"], float(raw["at"])
        if not isinstance(result, dict) or not math.isfinite(at):
            return None, 0.0
        if not isinstance(result.get(_KEYS[name]), list):
            return None, 0.0
        return result, max(0.0, time.time() - at)
    except (OSError, ValueError, KeyError, TypeError):
        return None, 0.0


def _write(name: str, directory: Path, result: dict) -> None:
    path = _path(name, directory)
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, temporary = tempfile.mkstemp(dir=directory, prefix=name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump({"at": time.time(), "result": result}, stream)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def _spawn_detached(argv: list[str]) -> None:
    # Poll completed children to reap them without waiting on active workers.
    _WORKERS[:] = [worker for worker in _WORKERS if worker.poll() is None]
    options: dict[str, Any] = {"stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL,
                               "stderr": subprocess.DEVNULL, "close_fds": True}
    if os.name == "nt":
        options["creationflags"] = 0x08000000 | 0x00000200  # NO_WINDOW | NEW_PROCESS_GROUP
    else:
        options["start_new_session"] = True
    _WORKERS.append(subprocess.Popen(argv, **options))  # nosec B603 -- argv is the fixed current interpreter + isolated cache_worker.py and validated probe key


def _start_refresh(name: str, directory: Path) -> None:
    # Probe the lease first to avoid spawning on every poll of a running scan.
    # The worker reacquires it and rechecks freshness: races can start a spare
    # process, but cannot run duplicate scans or overwrite a fresh result.
    with cache_lease(_path(name, directory).with_suffix(".lease")) as free:
        if not free:
            return
    script = Path(__file__).with_name("cache_worker.py")
    _spawn_detached([sys.executable, "-I", str(script), name, str(directory)])


def cached_probe(name: str) -> dict:
    directory = _cache_dir()
    result, age = _read(name, directory)
    error = None
    if result is None or age > _TTL_SEC:
        try:
            _start_refresh(name, directory)
        except (OSError, RuntimeError) as exc:
            error = f"{type(exc).__name__}: {exc}"
            _LOG.warning("inventory cache refresh unavailable for %s: %s", name, exc)
    out: dict[str, Any] = dict(result) if result is not None else {"available": False, _KEYS[name]: []}
    out["cache"] = {"state": "ready" if result is not None else "pending", "age_sec": round(age, 1)}
    if error:
        out["cache"]["error"] = error
    return out


def refresh_probe(name: str, directory: Path, collector: Callable[[], dict]) -> bool:
    """Worker entry: collect once, preserving an old answer on probe failure."""
    with cache_lease(_path(name, directory).with_suffix(".lease")) as held:
        if not held:
            return False
        previous, age = _read(name, directory)
        if previous is not None and age <= _TTL_SEC:
            return False
        result: dict[str, Any]
        try:
            result = collector()
            if not isinstance(result, dict) or not isinstance(result.get(_KEYS[name]), list):
                raise ValueError("collector returned an invalid inventory shape")
        except Exception as exc:
            result = dict(previous) if previous is not None else {"available": False, _KEYS[name]: []}
            result["error"] = f"{type(exc).__name__}: {exc}"
        _write(name, directory, result)
        return True


def cached_python_venvs() -> dict:
    return cached_probe("python_venvs")


def cached_git_repos() -> dict:
    return cached_probe("git_repos")
