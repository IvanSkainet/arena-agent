"""Mission recovery helpers that bridge mission state back into follow-up planning."""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

from arena.resources.mission_catalog import extract_failed_steps
from arena.resources.mission_lineage import build_followup_lineage
from arena.resources.mission_state import get_mission_history, get_mission_report, get_mission_status



def _recovery_reflection_goal(mission: dict[str, Any]) -> str:
    return f"Recover mission {mission.get('title') or mission.get('name') or mission.get('id') or 'mission'}"



def _build_recovery_run(mission: dict[str, Any], latest_run: dict[str, Any], failed_steps: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "goal": _recovery_reflection_goal(mission),
        "plan": {"steps": [{"title": f"Inspect failed mission step {item['step']}", "reason": item.get("cmd", "") or f"Mission step {item['step']} returned {item.get('exit_code')}"} for item in failed_steps[:3]]},
        "iterations": [{"iteration": idx, "action": {"name": f"mission.step.{idx}"}, "observation": {"ok": int(result.get("exit_code", 0) or 0) == 0, "exit_code": result.get("exit_code"), "cmd": result.get("cmd", "")}} for idx, result in enumerate(list(latest_run.get("results") or []), start=1)],
    }



def _followup_goal(mission: dict[str, Any], failed_steps: list[dict[str, Any]], reflection: dict[str, Any] | None, provided_goal: str) -> str:
    goal = str(provided_goal or "").strip()
    if goal:
        return goal
    title = mission.get("title") or mission.get("name") or mission.get("id") or "mission"
    if failed_steps:
        item = failed_steps[0]
        cmd = item.get("cmd", "") or f"step {item.get('step')}"
        return f"Recover and improve mission '{title}' after failure in {cmd}"
    if str(mission.get("state", "")) == "done":
        next_steps = list((reflection or {}).get("suggested_next_steps") or [])
        if next_steps:
            return f"Create a follow-up mission for '{title}': {next_steps[0]}"
        return f"Create a follow-up mission for '{title}' based on its latest successful run"
    return f"Continue mission '{title}' from its current state"



def _followup_context(mission: dict[str, Any], failed_steps: list[dict[str, Any]], reflection: dict[str, Any] | None, report_excerpt: str) -> str:
    lines = [f"Original mission id: {mission.get('id')}", f"Original mission title: {mission.get('title')}", f"Original goal: {mission.get('goal', '')}", f"Original state: {mission.get('state', '')}", f"Original template: {mission.get('template', '')}"]
    if failed_steps:
        lines.append("Latest failed steps:")
        lines.extend(f"- step {item['step']}: exit={item.get('exit_code')} cmd={item.get('cmd', '')}" for item in failed_steps[:5])
    if reflection:
        for label, key in (("Reflection positives:", "positives"), ("Reflection concerns:", "concerns"), ("Reflection suggested next steps:", "suggested_next_steps")):
            values = list(reflection.get(key) or [])
            if values:
                lines.append(label)
                lines.extend(f"- {entry}" for entry in values[:5])
    if report_excerpt:
        lines += ["Latest report excerpt:", report_excerpt]
    return "\n".join(line for line in lines if line)



def recover_mission_bundle(
    *,
    missions_dir,
    mission_id: str,
    notes: str = "",
    failed_only: bool = True,
    step: int | None = None,
    timeout: int = 180,
    rerun_now: bool = False,
    compose_followup: bool = False,
    create_followup: bool = False,
    followup_goal: str = "",
    followup_title: str = "",
    followup_mission_id: str = "",
    max_steps: int = 8,
    memory_profile: str | None = None,
    template: str = "",
    overwrite: bool = False,
    reflect_sync: Callable[..., dict[str, Any]] | None = None,
    compose_sync: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
    create_sync: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
    rerun_sync: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    mission_id = str(mission_id or "").strip()
    if not mission_id:
        return {"ok": False, "error": "missing mission_id", "status": 400}
    status = get_mission_status(missions_dir, mission_id)
    if not status.get("ok"):
        return status
    history = get_mission_history(missions_dir, mission_id)
    if not history.get("ok"):
        return history
    mission = history.get("mission") or status.get("mission") or {}
    latest_run = mission.get("latest_run") or {}
    failed_steps = extract_failed_steps(latest_run)
    effective_step = int(step) if step is not None else (failed_steps[0]["step"] if failed_only and failed_steps else None)
    report = get_mission_report(missions_dir, mission_id) if mission.get("report_exists") else {"ok": False}
    report_excerpt = str(report.get("content", "") or "")[:2000] if report.get("ok") else ""
    reflection = reflect_sync(goal=_recovery_reflection_goal(mission), run=_build_recovery_run(mission, latest_run, failed_steps), notes=notes, outcome=f"mission_recovery:{mission.get('state', 'unknown')}") if reflect_sync else None
    suggested_action = "inspect_mission"
    if step is not None:
        suggested_action = "rerun_specific_step"
    elif effective_step is not None:
        suggested_action = "rerun_failed_step"
    elif not latest_run:
        suggested_action = "run_mission"
    elif str(mission.get("state", "")) in {"failed", "error"}:
        suggested_action = "rerun_full_mission"
    elif str(mission.get("state", "")) == "done":
        suggested_action = "followup_or_inspect_report"
    suggested_rerun = {"mission_id": mission_id, "failed_only": bool(failed_only), "step": effective_step, "timeout": int(timeout or 180)}
    result: dict[str, Any] = {"ok": True, "goal": _recovery_reflection_goal(mission), "mission": mission, "history": {"runs_count": len(history.get("runs") or []), "latest_run": latest_run, "failed_steps": failed_steps, "step_logs": history.get("step_logs") or [], "report_excerpt": report_excerpt}, "recovery": {"notes": notes, "reflection": reflection, "suggested_action": suggested_action, "suggested_rerun": suggested_rerun}}
    if compose_followup or create_followup:
        if compose_sync is None:
            return {"ok": False, "error": "compose_sync unavailable", "status": 500, **result}
        next_goal = _followup_goal(mission, failed_steps, reflection, followup_goal)
        next_title = str(followup_title or "").strip() or f"Follow-up: {mission.get('title') or mission_id}"
        composed = compose_sync({"goal": next_goal, "context": _followup_context(mission, failed_steps, reflection, report_excerpt), "constraints": list(mission.get("constraints") or []), "max_steps": int(max_steps or 8), "memory_profile": memory_profile or mission.get("memory_profile") or "default", "title": next_title, "template": template or mission.get("template") or ""})
        if composed.get("ok") and isinstance(composed.get("draft"), dict):
            composed["draft"]["lineage"] = build_followup_lineage(mission, origin="recover", recovery=result["recovery"])
        result["recovery"]["followup"] = {"goal": next_goal, "title": next_title, "composed": composed}
        if not composed.get("ok"):
            result["ok"] = False
            result["status"] = int(composed.get("status", 400))
            return result
        if create_followup:
            if create_sync is None:
                result["ok"] = False
                result["status"] = 500
                result["recovery"]["followup"]["created"] = {"ok": False, "error": "create_sync unavailable", "status": 500}
                return result
            created = create_sync({"draft": composed.get("draft"), "mission_id": followup_mission_id, "overwrite": overwrite})
            result["recovery"]["followup"]["created"] = created
            if not created.get("ok"):
                result["ok"] = False
                result["status"] = int(created.get("status", 400))
                return result
    if rerun_now:
        if rerun_sync is None:
            result["ok"] = False
            result["status"] = 500
            result["recovery"]["rerun"] = {"ok": False, "error": "rerun_sync unavailable", "status": 500}
            return result
        rerun = rerun_sync(suggested_rerun)
        result["recovery"]["rerun"] = rerun
        if not rerun.get("ok"):
            result["ok"] = False
            result["status"] = int(rerun.get("status", 400))
    return result


__all__ = ["recover_mission_bundle"]
