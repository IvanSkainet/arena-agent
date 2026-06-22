"""Structured mission status/report inspection helpers."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def _mission_dir(missions_dir: Path, name: str) -> Path:
    if ".." in name or "/" in name or "\\" in name or name.startswith("."):
        raise ValueError("invalid mission name")
    return missions_dir / name



def summarize_mission_dir(path: Path) -> dict[str, Any]:
    mission_file = path / "mission.json"
    data: dict[str, Any] = {}
    if mission_file.exists():
        try:
            data = json.loads(mission_file.read_text(encoding="utf-8"))
        except Exception:
            data = {}
    runs = list(data.get("runs") or [])
    latest_run = runs[-1] if runs else None
    report = path / "REPORT.md"
    logs = path / "logs"
    return {
        "id": data.get("id", path.name),
        "name": path.name,
        "title": data.get("title", path.name),
        "template": data.get("template", ""),
        "state": data.get("state", "unknown"),
        "created_at": data.get("created_at", ""),
        "started_at": data.get("started_at", ""),
        "finished_at": data.get("finished_at", ""),
        "runs_count": len(runs),
        "latest_run": latest_run,
        "report_exists": report.exists(),
        "report_path": str(report) if report.exists() else None,
        "log_count": len(list(logs.glob("step-*.json"))) if logs.exists() else 0,
        "path": str(path),
    }



def get_mission_status(missions_dir: Path, name: str) -> dict[str, Any]:
    try:
        path = _mission_dir(missions_dir, name)
    except ValueError as exc:
        return {"ok": False, "error": str(exc), "status": 400}
    if not path.exists() or not path.is_dir():
        return {"ok": False, "error": f"mission '{name}' not found", "status": 404}
    return {"ok": True, "mission": summarize_mission_dir(path)}



def get_mission_report(missions_dir: Path, name: str) -> dict[str, Any]:
    status = get_mission_status(missions_dir, name)
    if not status.get("ok"):
        return status
    report_value = status["mission"].get("report_path")
    if not report_value:
        return {"ok": False, "error": f"report for mission '{name}' not found", "status": 404, "mission": status["mission"]}
    report_path = Path(report_value)
    if not report_path.exists() or not report_path.is_file():
        return {"ok": False, "error": f"report for mission '{name}' not found", "status": 404, "mission": status["mission"]}
    return {"ok": True, "mission": status["mission"], "content": report_path.read_text(encoding="utf-8", errors="replace"), "path": str(report_path)}


__all__ = ["get_mission_report", "get_mission_status", "summarize_mission_dir"]
