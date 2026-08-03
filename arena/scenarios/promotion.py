"""Promote successful scenario run/history into reusable scenarios."""
from __future__ import annotations

import re
from typing import Any

from arena.scenarios.mission_bridge import ScenarioMissionStore
from arena.scenarios.storage import render_scenario_source, validate_name


def _safe_step_id(raw: str, idx: int) -> str:
    sid = str(raw or f"step{idx}").strip()
    sid = re.sub(r"[^A-Za-z0-9_-]+", "_", sid)[:48]
    return sid or f"step{idx}"


def scenario_from_run(run: dict[str, Any], *, name: str, title: str | None = None,
                      description: str | None = None) -> dict[str, Any]:
    if not isinstance(run, dict):
        raise ValueError("run must be an object")
    scenario_name = validate_name(name)
    steps = []
    seen: set[str] = set()
    for idx, step in enumerate(run.get("steps") or [], start=1):
        if not isinstance(step, dict):
            continue
        tool = str(step.get("tool") or "").strip()
        if not tool:
            continue
        sid = _safe_step_id(str(step.get("id") or ""), idx)
        base = sid
        n = 2
        while sid in seen:
            sid = f"{base}_{n}"
            n += 1
        seen.add(sid)
        args = step.get("arguments") if isinstance(step.get("arguments"), dict) else {}
        promoted: dict[str, Any] = {"id": sid, "tool": tool, "arguments": args}
        if step.get("ok") is False:
            promoted["continue_on_error"] = True
        steps.append(promoted)
    if not steps:
        raise ValueError("run contains no promotable tool steps")
    doc = {
        "name": scenario_name,
        "title": title or f"Promoted from {run.get('name') or 'run'}",
        "description": description or f"Promoted from scenario run at {run.get('finished_at') or run.get('recorded_at') or 'unknown time'}.",
        "steps": steps,
    }
    doc["steps"].append({"id": "return_summary", "return": {"promoted_from": run.get("name"), "step_count": len(steps)}})
    return doc


def promote_from_run(run: dict[str, Any], *, name: str, overwrite: bool = True,
                     title: str | None = None, description: str | None = None,
                     storage: ScenarioMissionStore | None = None) -> dict[str, Any]:
    store = storage or ScenarioMissionStore()
    doc = scenario_from_run(run, name=name, title=title, description=description)
    source = render_scenario_source(doc)
    saved = store.save(name, source, overwrite=overwrite)
    return {"ok": True, "name": saved["name"], "mission_id": saved["mission_id"], "path": saved["path"],
            "step_count": saved["step_count"], "source": source, "doc": doc}


def promote_from_history(source: str, *, name: str, index: int = -1, overwrite: bool = True,
                         title: str | None = None, description: str | None = None,
                         storage: ScenarioMissionStore | None = None) -> dict[str, Any]:
    store = storage or ScenarioMissionStore()
    runs = store.load_history(source)
    if not runs:
        return {"ok": False, "error": "source scenario has no history", "source": source}
    try:
        run = runs[index]
    except Exception:
        return {"ok": False, "error": f"history index out of range: {index}", "source": source, "count": len(runs)}
    out = promote_from_run(run, name=name, overwrite=overwrite, title=title, description=description, storage=store)
    out["source"] = source
    out["history_index"] = index
    out["source_run"] = run
    return out


__all__ = ["scenario_from_run", "promote_from_run", "promote_from_history"]
