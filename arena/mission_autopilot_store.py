"""Persistence layer for Mission Autopilot runs.

Split out of ``arena/mission_autopilot.py`` so the orchestration module stays
under the mini-monolith line threshold enforced by
``tests/test_architecture_boundaries.py``.  This module owns exactly one
concern: where a run lives on disk, and how it is read and written safely.

The public names are re-exported from ``arena.mission_autopilot`` so every
existing caller (and every test that monkeypatches ``_run_path`` or
``_load``) keeps working unchanged.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import re
import threading
from pathlib import Path
from typing import Any

from arena.jsonshape import loads_object

# Guards concurrent read/write of run JSON files: without it a reader can
# observe a half-written file and a concurrent writer can lose an update.
_file_lock = threading.Lock()


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def _slug(value: str, fallback: str = "autopilot") -> str:
    s = re.sub(r"[^a-zA-Z0-9._-]+", "-", str(value or "").strip()).strip("-").lower()
    return s[:70] or fallback


def _home() -> Path:
    return Path(os.environ.get("ARENA_AGENT_HOME", str(Path.home() / "arena-bridge"))).expanduser()


def _runs_dir() -> Path:
    p = _home() / "autopilot" / "runs"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _run_path(run_id: str) -> Path:
    return _runs_dir() / f"{_slug(run_id)}.json"


def _save(run: dict[str, Any]) -> None:
    """Persist a run file, guarded by a lock to prevent concurrent-write races."""
    with _file_lock:
        _run_path(run["run_id"]).write_text(
            json.dumps(run, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _load(run_id: str) -> dict[str, Any]:
    """Load a run file, guarded by a lock to prevent reading mid-write."""
    with _file_lock:
        p = _run_path(run_id)
        if not p.exists():
            raise FileNotFoundError(run_id)
        return loads_object(p.read_text(encoding="utf-8"))


def _missing_run(run_id: str) -> dict[str, Any]:
    """The structured answer every run-scoped entry point owes its caller.

    ``_load`` raises ``FileNotFoundError(run_id)``, and with an empty run_id
    that is an exception carrying no message at all: the MCP dispatcher's
    catch-all rendered it as the literal text ``ERROR: FileNotFoundError:``.
    A model reading that is told nothing -- not which run, not that the
    argument was missing, not that retrying is pointless.  Every other tool
    in the surface answers with ``{"ok": false, "error": ...}``; the five
    run-scoped autopilot tools now do too.
    """
    if not run_id:
        return {"ok": False, "error": "run_id is required", "run_id": ""}
    return {"ok": False, "error": "run_not_found", "run_id": run_id,
            "hint": "list existing runs with mission.autopilot_list"}


__all__ = ["_file_lock", "_home", "_load", "_missing_run", "_now",
           "_run_path", "_runs_dir", "_save", "_slug"]
