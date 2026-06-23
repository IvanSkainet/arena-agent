"""High-level mission follow-up and iteration loops."""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

from arena.resources.mission_lineage import build_followup_lineage
from arena.resources.mission_recovery import _followup_context, _followup_goal, recover_mission_bundle



def _source_constraints(mission: dict[str, Any], constraints: list[str] | None) -> list[str]:
    return list(constraints if constraints is not None else mission.get("constraints") or [])



def _source_profile(mission: dict[str, Any], memory_profile: str | None) -> str:
    return str(memory_profile or mission.get("memory_profile") or "default")



def followup_mission_bundle(
    *,
    recovery: dict[str, Any] | None = None,
    missions_dir=None,
    mission_id: str = "",
    goal: str = "",
    title: str = "",
    notes: str = "",
    constraints: list[str] | None = None,
    max_steps: int = 8,
    max_iterations: int = 4,
    memory_profile: str | None = None,
    template: str = "",
    url: str = "",
    origin: str = "followup",
    create: bool = False,
    run_now: bool = False,
    followup_mission_id: str = "",
    overwrite: bool = False,
    timeout: int = 180,
    react_sync: Callable[..., dict[str, Any]] | None = None,
    reflect_sync: Callable[..., dict[str, Any]] | None = None,
    compose_sync: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
    create_sync: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
    run_sync: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    if recovery is None:
        recovery = recover_mission_bundle(missions_dir=missions_dir, mission_id=mission_id, notes=notes, reflect_sync=reflect_sync)
    if not recovery.get("ok"):
        return recovery
    mission = recovery.get("mission") or {}
    history = recovery.get("history") or {}
    recovery_data = recovery.get("recovery") or {}
    failed_steps = list(history.get("failed_steps") or [])
    next_goal = _followup_goal(mission, failed_steps, recovery_data.get("reflection"), goal)
    next_title = str(title or "").strip() or f"Follow-up: {mission.get('title') or mission.get('name') or mission.get('id') or 'mission'}"
    next_context = _followup_context(mission, failed_steps, recovery_data.get("reflection"), str(history.get("report_excerpt", "") or ""))
    final_constraints = _source_constraints(mission, constraints)
    final_profile = _source_profile(mission, memory_profile)
    react = react_sync(goal=next_goal, context=next_context, constraints=final_constraints, max_iterations=max_iterations, memory_profile=final_profile, url=url)
    reflection = reflect_sync(goal=next_goal, run=react, notes=notes, outcome="mission_followup")
    composed = compose_sync({"goal": next_goal, "context": next_context, "constraints": final_constraints, "max_steps": max_steps, "memory_profile": final_profile, "title": next_title, "template": template or mission.get("template") or ""})
    if not composed.get("ok"):
        return {"ok": False, "status": int(composed.get("status", 400)), "source_mission": mission, "history": history, "recovery": recovery_data, "react": react, "reflection": reflection, "followup": {"goal": next_goal, "title": next_title, "context": next_context, "composed": composed}}
    draft = dict(composed.get("draft") or {})
    draft["lineage"] = build_followup_lineage(mission, origin=origin, recovery=recovery_data)
    draft["analysis"] = {
        **dict(draft.get("analysis") or {}),
        "source_mission": {"id": mission.get("id"), "title": mission.get("title"), "state": mission.get("state"), "template": mission.get("template")},
        "recovery": recovery_data,
        "history": {"failed_steps": failed_steps, "latest_run": mission.get("latest_run"), "report_excerpt": history.get("report_excerpt", "")},
        "react_summary": react.get("summary", ""),
        "react_iterations": react.get("iterations", []),
        "reflection": reflection,
    }
    result: dict[str, Any] = {"ok": True, "source_mission": mission, "history": history, "recovery": recovery_data, "react": react, "reflection": reflection, "followup": {"goal": next_goal, "title": next_title, "context": next_context, "lineage": draft.get("lineage"), "draft": draft, "template_data": composed.get("template_data"), "plan": composed.get("plan")}}
    created = None
    if create:
        created = create_sync({"draft": draft, "mission_id": followup_mission_id, "overwrite": overwrite})
        result["followup"]["created"] = created
        if not created.get("ok"):
            result["ok"] = False
            result["status"] = int(created.get("status", 400))
            return result
    if run_now:
        if not create:
            created = create_sync({"draft": draft, "mission_id": followup_mission_id, "overwrite": overwrite})
            result["followup"]["created"] = created
            if not created.get("ok"):
                result["ok"] = False
                result["status"] = int(created.get("status", 400))
                return result
        run = run_sync({"mission_id": created.get("mission_id"), "timeout": timeout})
        result["followup"]["run"] = run
        if not run.get("ok"):
            result["ok"] = False
            result["status"] = int(run.get("status", 400))
    return result



def iterate_mission_bundle(
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
    run_followup: bool = False,
    followup_goal: str = "",
    followup_title: str = "",
    followup_mission_id: str = "",
    constraints: list[str] | None = None,
    max_steps: int = 8,
    max_iterations: int = 4,
    memory_profile: str | None = None,
    template: str = "",
    url: str = "",
    overwrite: bool = False,
    react_sync: Callable[..., dict[str, Any]] | None = None,
    reflect_sync: Callable[..., dict[str, Any]] | None = None,
    compose_sync: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
    create_sync: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
    rerun_sync: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
    run_sync: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    recovery = recover_mission_bundle(missions_dir=missions_dir, mission_id=mission_id, notes=notes, failed_only=failed_only, step=step, timeout=timeout, rerun_now=rerun_now, reflect_sync=reflect_sync, rerun_sync=rerun_sync)
    if not recovery.get("ok"):
        return recovery
    decision = {"source_state": recovery.get("mission", {}).get("state"), "suggested_action": recovery.get("recovery", {}).get("suggested_action"), "prefer_rerun_first": recovery.get("recovery", {}).get("suggested_action") in {"rerun_failed_step", "rerun_specific_step", "rerun_full_mission"} and not rerun_now}
    result: dict[str, Any] = {"ok": True, "source_mission": recovery.get("mission"), "history": recovery.get("history"), "recovery": recovery.get("recovery"), "decision": decision, "mode": "recover_and_followup" if (compose_followup or create_followup or run_followup) else "recover_only"}
    if compose_followup or create_followup or run_followup:
        followup = followup_mission_bundle(recovery=recovery, goal=followup_goal, title=followup_title, notes=notes, constraints=constraints, max_steps=max_steps, max_iterations=max_iterations, memory_profile=memory_profile, template=template, url=url, origin="iterate", create=create_followup or run_followup, run_now=run_followup, followup_mission_id=followup_mission_id, overwrite=overwrite, timeout=timeout, react_sync=react_sync, reflect_sync=reflect_sync, compose_sync=compose_sync, create_sync=create_sync, run_sync=run_sync)
        result["followup"] = followup.get("followup")
        result["react"] = followup.get("react")
        result["reflection"] = followup.get("reflection")
        if not followup.get("ok"):
            result["ok"] = False
            result["status"] = int(followup.get("status", 400))
    return result


__all__ = ["followup_mission_bundle", "iterate_mission_bundle"]
