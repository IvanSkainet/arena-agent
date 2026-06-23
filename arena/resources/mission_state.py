"""Structured mission status/history/report inspection helpers."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any



def _mission_dir(missions_dir: Path, name: str) -> Path:
    if ".." in name or "/" in name or "\\" in name or name.startswith("."):
        raise ValueError("invalid mission name")
    return missions_dir / name



def _load_mission_json(path: Path) -> dict[str, Any]:
    mission_file = path / "mission.json"
    if not mission_file.exists():
        return {}
    try:
        return json.loads(mission_file.read_text(encoding="utf-8"))
    except Exception:
        return {}



def summarize_mission_dir(path: Path) -> dict[str, Any]:
    data = _load_mission_json(path)
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



def get_mission_history(missions_dir: Path, name: str) -> dict[str, Any]:
    status = get_mission_status(missions_dir, name)
    if not status.get("ok"):
        return status
    path = Path(status["mission"]["path"])
    data = _load_mission_json(path)
    logs_dir = path / "logs"
    step_logs = []
    if logs_dir.exists():
        for log_path in sorted(logs_dir.glob("step-*.json")):
            try:
                entry = json.loads(log_path.read_text(encoding="utf-8"))
            except Exception:
                entry = {"cmd": "", "exit_code": None}
            step_logs.append({"name": log_path.stem, "path": str(log_path), "cmd": entry.get("cmd", ""), "exit_code": entry.get("exit_code")})
    return {"ok": True, "mission": status["mission"], "runs": list(data.get("runs") or []), "step_logs": step_logs}



def infer_rerun_step(missions_dir: Path, name: str, *, failed_only: bool = False) -> dict[str, Any]:
    history = get_mission_history(missions_dir, name)
    if not history.get("ok"):
        return history
    if not failed_only:
        return {"ok": True, "step": None, "mission": history["mission"]}
    latest = history.get("mission", {}).get("latest_run") or {}
    results = list(latest.get("results") or [])
    if not results:
        return {"ok": False, "error": "no previous run results to infer failed step", "status": 409, "mission": history["mission"]}
    for idx, result in enumerate(results, start=1):
        if int(result.get("exit_code", 0) or 0) != 0:
            return {"ok": True, "step": idx, "mission": history["mission"]}
    return {"ok": False, "error": "latest run has no failed step", "status": 409, "mission": history["mission"]}


__all__ = ["get_mission_history", "get_mission_report", "get_mission_status", "infer_rerun_step", "summarize_mission_dir"]
