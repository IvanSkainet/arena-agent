"""Structured mission status/history/report inspection helpers."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from arena.resources.mission_catalog import catalog_missions, extract_failed_steps, load_mission_json, mission_dir, summarize_mission_dir



def get_mission_status(missions_dir: Path, name: str) -> dict[str, Any]:
    try:
        path = mission_dir(missions_dir, name)
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
    data = load_mission_json(path)
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
    failed_steps = extract_failed_steps(latest)
    if not latest:
        return {"ok": False, "error": "no previous run results to infer failed step", "status": 409, "mission": history["mission"]}
    if failed_steps:
        return {"ok": True, "step": failed_steps[0]["step"], "mission": history["mission"]}
    return {"ok": False, "error": "latest run has no failed step", "status": 409, "mission": history["mission"]}


__all__ = ["catalog_missions", "extract_failed_steps", "get_mission_history", "get_mission_report", "get_mission_status", "infer_rerun_step", "summarize_mission_dir"]
