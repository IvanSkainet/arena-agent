"""Mission proposal/orchestration helpers that combine agentic runs with mission composition."""
from __future__ import annotations

from typing import Any, Callable

from arena.resources.mission_recovery import recover_mission_bundle



def propose_mission_bundle(
    *,
    goal: str,
    context: str = "",
    constraints: list[str] | None = None,
    max_steps: int = 8,
    max_iterations: int = 4,
    memory_profile: str | None = None,
    url: str = "",
    template: str = "",
    title: str = "",
    notes: str = "",
    create: bool = False,
    mission_id: str = "",
    overwrite: bool = False,
    run_now: bool = False,
    timeout: int = 180,
    react_sync: Callable[..., dict[str, Any]] = None,
    reflect_sync: Callable[..., dict[str, Any]] = None,
    compose_sync: Callable[[dict[str, Any]], dict[str, Any]] = None,
    create_sync: Callable[[dict[str, Any]], dict[str, Any]] = None,
    run_sync: Callable[[dict[str, Any]], dict[str, Any]] = None,
) -> dict[str, Any]:
    goal = str(goal or "").strip()
    if not goal:
        return {"ok": False, "error": "missing goal", "status": 400}
    constraints = constraints or []
    react = react_sync(goal=goal, context=context, constraints=constraints, max_iterations=max_iterations, memory_profile=memory_profile, url=url)
    reflection = reflect_sync(goal=goal, run=react, notes=notes, outcome="mission_proposal")
    composed = compose_sync({"goal": goal, "context": context, "constraints": constraints, "max_steps": max_steps, "memory_profile": memory_profile, "title": title, "template": template})
    if not composed.get("ok"):
        return composed
    draft = dict(composed.get("draft") or {})
    draft["analysis"] = {"react_summary": react.get("summary", ""), "react_iterations": react.get("iterations", []), "reflection": reflection}
    result: dict[str, Any] = {"ok": True, "goal": goal, "react": react, "reflection": reflection, "mission": {"draft": draft, "template_data": composed.get("template_data"), "plan": composed.get("plan")}}
    created = None
    if create:
        created = create_sync({"draft": draft, "mission_id": mission_id, "overwrite": overwrite})
        result["mission"]["created"] = created
        if not created.get("ok"):
            result["ok"] = False
            result["status"] = int(created.get("status", 400))
            return result
    if run_now:
        if not create:
            created = create_sync({"draft": draft, "mission_id": mission_id, "overwrite": overwrite})
            result["mission"]["created"] = created
            if not created.get("ok"):
                result["ok"] = False
                result["status"] = int(created.get("status", 400))
                return result
        run = run_sync({"mission_id": created.get("mission_id"), "timeout": timeout})
        result["mission"]["run"] = run
        if not run.get("ok"):
            result["ok"] = False
            result["status"] = int(run.get("status", 400))
    return result


__all__ = ["propose_mission_bundle", "recover_mission_bundle"]
