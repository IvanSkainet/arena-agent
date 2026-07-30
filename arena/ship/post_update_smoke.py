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
    pending = None
    last = None
    if pending_path().exists():
        try:
            pending = json.loads(pending_path().read_text(encoding="utf-8"))
        except Exception as e:
            pending = {"ok": False, "error": str(e)}
    if last_path().exists():
        try:
            last = json.loads(last_path().read_text(encoding="utf-8"))
        except Exception as e:
            last = {"ok": False, "error": str(e)}
    return {"ok": True, "pending": pending is not None, "pending_record": pending, "last": last}


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
