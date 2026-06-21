"""Bounded ReAct loop and reflection helpers."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable


@dataclass(frozen=True)
class AgenticRuntimeContext:
    build_plan: Callable[..., dict[str, Any]]
    recall_sync: Callable[..., dict[str, Any]]
    common_status: Callable[[dict[str, Any]], dict[str, Any]]
    app_config: Callable[[], dict[str, Any]]
    doctor_sync: Callable[[str], dict[str, Any]]
    sysinfo_sync: Callable[[Any], dict[str, Any]]
    tasks_list_sync: Callable[..., dict[str, Any]]
    file_watch_list_sync: Callable[[], dict[str, Any]]
    browser_head_sync: Callable[[str], dict[str, Any]]


@dataclass(frozen=True)
class AgenticRuntime:
    react_sync: Callable[..., dict[str, Any]]
    reflect_sync: Callable[..., dict[str, Any]]



def _safe_browser_head(url: str, browser_head_sync: Callable[[str], dict[str, Any]]) -> dict[str, Any] | None:
    url = str(url or "").strip()
    if not url:
        return None
    return browser_head_sync(url)



def _choose_actions(plan: dict[str, Any], *, url: str = "") -> list[tuple[str, Callable[[], Any], str]]:
    actions: list[tuple[str, Callable[[], Any], str]] = []
    required = set(plan.get("required_tools") or [])
    if "memory.recall" in required:
        actions.append(("memory.recall", lambda: None, "Recover relevant memory for the goal."))
    if "/v1/status" in required:
        actions.append(("bridge.status", lambda: None, "Check current bridge/runtime state."))
    if url and "/v1/browser/head" in required:
        actions.append(("browser.head", lambda: None, "Check the target URL headers and reachability."))
    if "/v1/doctor" in required:
        actions.append(("system.doctor", lambda: None, "Verify environment health before acting."))
    if "/v1/sysinfo" in required:
        actions.append(("system.sysinfo", lambda: None, "Collect current machine state."))
    if "/v1/tasks" in required:
        actions.append(("tasks.list", lambda: None, "Inspect current task queue state."))
    if "/v1/watch/files" in required:
        actions.append(("watch.files.list", lambda: None, "Inspect active file watchers."))
    if not actions:
        actions.append(("bridge.status", lambda: None, "Start by checking bridge status."))
    return actions



def make_agentic_runtime(ctx: AgenticRuntimeContext) -> AgenticRuntime:
    def react_sync(
        *,
        goal: str,
        context: str = "",
        constraints: list[str] | None = None,
        max_iterations: int = 4,
        memory_profile: str | None = None,
        url: str = "",
    ) -> dict[str, Any]:
        plan = ctx.build_plan(
            goal=goal,
            context=context,
            constraints=constraints or [],
            max_steps=max(3, min(8, max_iterations + 2)),
            memory_profile=memory_profile,
        )
        profile = plan.get("suggested_memory_profile", memory_profile or "default")
        actions = _choose_actions(plan, url=url)
        cfg = ctx.app_config() or {}
        iterations = []
        for idx, (action_name, _noop, reason) in enumerate(actions[:max_iterations], start=1):
            if action_name == "memory.recall":
                observation = ctx.recall_sync(goal, 5, profile)
            elif action_name == "bridge.status":
                observation = ctx.common_status(cfg)
            elif action_name == "system.doctor":
                observation = ctx.doctor_sync(cfg.get("token", ""))
            elif action_name == "system.sysinfo":
                observation = ctx.sysinfo_sync(cfg.get("root"))
            elif action_name == "tasks.list":
                observation = ctx.tasks_list_sync("", 20)
            elif action_name == "watch.files.list":
                observation = ctx.file_watch_list_sync()
            elif action_name == "browser.head":
                observation = _safe_browser_head(url, ctx.browser_head_sync) or {"ok": False, "error": "missing url"}
            else:
                observation = {"ok": False, "error": f"unknown action: {action_name}"}
            iterations.append(
                {
                    "iteration": idx,
                    "reason": reason,
                    "action": {"name": action_name},
                    "observation": observation,
                }
            )
        return {
            "ok": True,
            "goal": goal,
            "context": context,
            "constraints": constraints or [],
            "memory_profile": profile,
            "plan": plan,
            "iterations": iterations,
            "next_action": plan.get("next_action", ""),
            "summary": f"Executed {len(iterations)} bounded observe steps for: {goal}",
        }

    def reflect_sync(
        *,
        goal: str,
        run: dict[str, Any] | None = None,
        notes: str = "",
        outcome: str = "",
    ) -> dict[str, Any]:
        run = run or {}
        iterations = run.get("iterations") or []
        positives = []
        concerns = []
        missing = []
        action_names = [it.get("action", {}).get("name", "") for it in iterations]
        if action_names:
            positives.append(f"Collected {len(action_names)} observation step(s): {', '.join(a for a in action_names if a)}")
        else:
            concerns.append("No observations were captured before reflection.")
        if "memory.recall" not in action_names:
            missing.append("No memory recall step was executed; the agent may be missing prior context.")
        if "bridge.status" not in action_names:
            missing.append("Bridge status was not checked; environment assumptions may be stale.")
        if any(not (it.get("observation") or {}).get("ok", True) for it in iterations if isinstance(it.get("observation"), dict)):
            concerns.append("At least one observation step returned an unsuccessful result.")
        if notes:
            positives.append("Operator notes were supplied and should be incorporated into the next plan.")
        confidence = "high" if iterations and not concerns and not missing else ("medium" if iterations else "low")
        suggested_next = []
        if missing:
            suggested_next.extend(missing)
        if not suggested_next and run.get("plan", {}).get("steps"):
            suggested_next.append(f"Proceed to execution with plan step: {run['plan']['steps'][0]['title']}")
        if outcome:
            positives.append(f"Recorded outcome: {outcome}")
        return {
            "ok": True,
            "goal": goal or run.get("goal", ""),
            "confidence": confidence,
            "positives": positives,
            "concerns": concerns,
            "missing_evidence": missing,
            "suggested_next_steps": suggested_next,
            "notes": notes,
        }

    return AgenticRuntime(react_sync=react_sync, reflect_sync=reflect_sync)
