"""Post-update smoke marker and startup hook."""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from arena.constants import VERSION
from arena.workbench.runtimes import home


def _dir() -> Path:
    p = home() / "update"
    p.mkdir(parents=True, exist_ok=True)
    return p


def pending_path() -> Path:
    return _dir() / "post-update-smoke-pending.json"


def last_path() -> Path:
    return _dir() / "post-update-smoke-last.json"


def mark_pending(data: dict[str, Any]) -> dict[str, Any]:
    doc = {"ok": True, "created_at": int(time.time()), "target_version": VERSION, **(data or {})}
    pending_path().write_text(json.dumps(doc, indent=2, ensure_ascii=False), encoding="utf-8")
    return {"ok": True, "pending_path": str(pending_path()), "pending": doc}


def status() -> dict[str, Any]:
    # Declared: both are either None or a decoded JSON object, and the reads
    # below (`last.get("smoke")`) only make sense for the dict case.
    pending: dict[str, Any] | None = None
    last: dict[str, Any] | None = None
    if pending_path().exists():
        try:
            loaded_pending = json.loads(pending_path().read_text(encoding="utf-8"))
            pending = loaded_pending if isinstance(loaded_pending, dict) else {"ok": False, "error": "pending record is not an object"}
        except Exception as e:
            pending = {"ok": False, "error": str(e)}
    if last_path().exists():
        try:
            loaded_last = json.loads(last_path().read_text(encoding="utf-8"))
            last = loaded_last if isinstance(loaded_last, dict) else {"ok": False, "error": "last record is not an object"}
        except Exception as e:
            last = {"ok": False, "error": str(e)}
    if pending is not None:
        state = "pending"
    elif isinstance(last, dict) and last.get("attempted"):
        state = "nominal" if last.get("ok") and (last.get("smoke") or {}).get("mode") == "nominal" else ("degraded" if last.get("ok") else "failed")
    else:
        state = "unknown"
    return {"ok": True, "state": state, "pending": pending is not None, "pending_record": pending, "last": last}


def run_if_pending() -> dict[str, Any]:
    p = pending_path()
    if not p.exists():
        return {"ok": True, "attempted": False, "reason": "no pending post-update smoke marker"}
    try:
        pending = json.loads(p.read_text(encoding="utf-8"))
    except Exception as e:
        pending = {"ok": False, "error": str(e)}
    try:
        from arena.ship import smoke
        report = smoke.run()
        outcome = {"ok": bool(report.get("ok")), "attempted": True, "ran_at": int(time.time()), "pending": pending,
                   "smoke": {"ok": report.get("ok"), "mode": report.get("mode"), "version": report.get("version"), "report_path": report.get("report_path"), "failed": report.get("failed", []), "warnings": report.get("warnings", [])}}
    except Exception as e:  # pragma: no cover
        outcome = {"ok": False, "attempted": True, "ran_at": int(time.time()), "pending": pending, "error": f"{type(e).__name__}: {e}"}
    last_path().write_text(json.dumps(outcome, indent=2, ensure_ascii=False), encoding="utf-8")
    try:
        p.unlink()
    except Exception:
        pass
    return outcome


__all__ = ["mark_pending", "status", "run_if_pending"]
