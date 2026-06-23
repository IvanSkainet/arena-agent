"""Mission file/catalog helpers shared across mission lifecycle surfaces."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any



def mission_dir(missions_dir: Path, name: str) -> Path:
    if ".." in name or "/" in name or "\\" in name or name.startswith("."):
        raise ValueError("invalid mission name")
    return missions_dir / name



def load_mission_json(path: Path) -> dict[str, Any]:
    mission_file = path / "mission.json"
    if not mission_file.exists():
        return {}
    try:
        return json.loads(mission_file.read_text(encoding="utf-8"))
    except Exception:
        return {}



def extract_failed_steps(run: dict[str, Any] | None) -> list[dict[str, Any]]:
    failed: list[dict[str, Any]] = []
    for idx, result in enumerate(list((run or {}).get("results") or []), start=1):
        exit_code = result.get("exit_code")
        if int(exit_code or 0) == 0:
            continue
        failed.append({
            "step": idx,
            "cmd": result.get("cmd", ""),
            "exit_code": exit_code,
            "stdout": str(result.get("stdout", "") or "")[-1000:],
            "stderr": str(result.get("stderr", "") or "")[-1000:],
            "ts": result.get("ts", ""),
        })
    return failed



def _latest_exit_code(run: dict[str, Any] | None) -> int | None:
    if not run:
        return None
    if "exit_code" in run and run.get("exit_code") is not None:
        try:
            return int(run.get("exit_code"))
        except Exception:
            return None
    results = list(run.get("results") or [])
    if not results:
        return 0 if run.get("ok") else None
    for result in results:
        code = int(result.get("exit_code", 0) or 0)
        if code != 0:
            return code
    return 0



def _last_activity(data: dict[str, Any], latest_run: dict[str, Any] | None) -> str:
    return (
        str((latest_run or {}).get("finished_at", "") or "")
        or str((latest_run or {}).get("ts", "") or "")
        or str(data.get("finished_at", "") or "")
        or str(data.get("started_at", "") or "")
        or str(data.get("created_at", "") or "")
    )



def summarize_mission_dir(path: Path) -> dict[str, Any]:
    data = load_mission_json(path)
    draft = data.get("draft") if isinstance(data.get("draft"), dict) else {}
    runs = list(data.get("runs") or [])
    latest_run = runs[-1] if runs else None
    latest_failed_steps = extract_failed_steps(latest_run)
    report = path / "REPORT.md"
    logs = path / "logs"
    return {
        "id": data.get("id", path.name),
        "name": path.name,
        "title": data.get("title", path.name),
        "goal": draft.get("goal", ""),
        "constraints": list(draft.get("constraints", []) or []),
        "template": data.get("template", draft.get("template", "")),
        "memory_profile": draft.get("suggested_memory_profile", "default"),
        "state": data.get("state", "unknown"),
        "created_at": data.get("created_at", ""),
        "started_at": data.get("started_at", ""),
        "finished_at": data.get("finished_at", ""),
        "last_activity_at": _last_activity(data, latest_run),
        "runs_count": len(runs),
        "latest_run": latest_run,
        "latest_exit_code": _latest_exit_code(latest_run),
        "failed_steps_count": len(latest_failed_steps),
        "latest_failed_steps": latest_failed_steps,
        "report_exists": report.exists(),
        "report_path": str(report) if report.exists() else None,
        "log_count": len(list(logs.glob("step-*.json"))) if logs.exists() else 0,
        "path": str(path),
    }



def catalog_missions(
    missions_dir: Path,
    *,
    state: str = "",
    template: str = "",
    query: str = "",
    has_report: bool | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    all_items = [
        summarize_mission_dir(path)
        for path in sorted(missions_dir.iterdir())
        if missions_dir.exists() and path.is_dir() and (path / "mission.json").exists()
    ] if missions_dir.exists() else []
    state_q = str(state or "").strip().lower()
    template_q = str(template or "").strip().lower()
    query_q = str(query or "").strip().lower()
    items: list[dict[str, Any]] = []
    for item in all_items:
        if state_q and str(item.get("state", "")).lower() != state_q:
            continue
        if template_q and str(item.get("template", "")).lower() != template_q:
            continue
        if has_report is not None and bool(item.get("report_exists")) is not bool(has_report):
            continue
        if query_q:
            haystack = " ".join(str(item.get(key, "") or "") for key in ("id", "name", "title", "goal", "template")).lower()
            if query_q not in haystack:
                continue
        items.append(item)
    items.sort(key=lambda item: (str(item.get("last_activity_at", "") or ""), str(item.get("created_at", "") or ""), str(item.get("name", "") or "")), reverse=True)
    offset = max(0, int(offset or 0))
    limit = max(1, min(200, int(limit or 50)))
    states: dict[str, int] = {}
    templates: dict[str, int] = {}
    for item in items:
        states[item.get("state", "unknown")] = states.get(item.get("state", "unknown"), 0) + 1
        key = item.get("template", "") or "unknown"
        templates[key] = templates.get(key, 0) + 1
    return {
        "ok": True,
        "total": len(all_items),
        "matched": len(items),
        "offset": offset,
        "limit": limit,
        "filters": {"state": state or None, "template": template or None, "query": query or None, "has_report": has_report},
        "stats": {
            "states": states,
            "templates": templates,
            "reports": sum(1 for item in items if item.get("report_exists")),
            "with_failures": sum(1 for item in items if int(item.get("failed_steps_count", 0) or 0) > 0),
        },
        "items": items[offset:offset + limit],
    }


__all__ = ["catalog_missions", "extract_failed_steps", "load_mission_json", "mission_dir", "summarize_mission_dir"]
