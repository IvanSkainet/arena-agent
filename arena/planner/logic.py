"""Goal-to-plan heuristics for the first built-in planner."""
from __future__ import annotations

from typing import Any

from arena.memory.profiles import normalize_memory_profile

_DOMAIN_KEYWORDS = {
    "browser": ("browser", "site", "web", "url", "search", "page", "http"),
    "code": ("code", "repo", "project", "bug", "fix", "refactor", "test", "implement", "python", "file"),
    "desktop": ("desktop", "window", "screen", "click", "type", "gui", "app"),
    "system": ("system", "service", "diagnose", "log", "restart", "process", "shell", "exec"),
    "task": ("long", "background", "monitor", "watch", "queue", "scheduled", "task"),
}


def _contains_any(text: str, words: tuple[str, ...]) -> bool:
    low = text.lower()
    return any(word in low for word in words)



def infer_memory_profile(goal: str, context: str = "", explicit_profile: str | None = None) -> str:
    if explicit_profile:
        return normalize_memory_profile(explicit_profile)
    text = f"{goal} {context}".lower()
    if _contains_any(text, _DOMAIN_KEYWORDS["code"]):
        return "code"
    if _contains_any(text, _DOMAIN_KEYWORDS["browser"]):
        return "browser"
    if any(word in text for word in ("preference", "name", "timezone", "personal")):
        return "personal"
    return "default"



def _domain_flags(goal: str, context: str = "") -> dict[str, bool]:
    text = f"{goal} {context}".lower()
    return {name: _contains_any(text, words) for name, words in _DOMAIN_KEYWORDS.items()}



def _step(step_id: int, title: str, reason: str, tools: list[str], *, confirm: bool = False) -> dict[str, Any]:
    return {
        "id": f"step_{step_id}",
        "title": title,
        "reason": reason,
        "suggested_tools": tools,
        "requires_confirmation": confirm,
    }



def build_plan(
    *,
    goal: str,
    context: str = "",
    constraints: list[str] | None = None,
    max_steps: int = 8,
    memory_profile: str | None = None,
) -> dict[str, Any]:
    goal = str(goal or "").strip()
    context = str(context or "").strip()
    constraints = [str(c).strip() for c in (constraints or []) if str(c).strip()]
    if not goal:
        raise ValueError("goal is required")
    max_steps = max(3, min(12, int(max_steps or 8)))
    profile = infer_memory_profile(goal, context, explicit_profile=memory_profile)
    flags = _domain_flags(goal, context)

    steps: list[dict[str, Any]] = [
        _step(1, "Scope the task and recover relevant context", f"Use memory profile '{profile}' and gather any existing facts before acting.", ["memory.recall", "/v1/status"]),
    ]
    risks = [
        "The planner is heuristic in v1 and should be reviewed before high-impact actions.",
    ]
    required_tools = {"memory.recall", "/v1/status"}

    if flags["code"]:
        steps.append(_step(len(steps) + 1, "Inspect repository state and relevant files", "Read the current code/tests before proposing changes.", ["fs.search", "fs.view", "git.status"]))
        required_tools.update({"fs.search", "fs.view", "git.status"})
        risks.append("Code tasks should validate tests before and after editing.")
    if flags["browser"]:
        steps.append(_step(len(steps) + 1, "Collect web evidence", "Gather the external information needed to complete the goal.", ["browser.search", "browser.read", "/v1/browser/head"]))
        required_tools.update({"browser.search", "browser.read", "/v1/browser/head"})
    if flags["desktop"]:
        steps.append(_step(len(steps) + 1, "Inspect the desktop state safely", "Capture screen/window context before performing GUI actions.", ["/v1/desktop/screenshot", "/v1/desktop/windows"], confirm=True))
        required_tools.update({"/v1/desktop/screenshot", "/v1/desktop/windows"})
        risks.append("Desktop actions can affect the live user session and may require confirmation.")
    if flags["system"]:
        steps.append(_step(len(steps) + 1, "Run safe diagnostics", "Collect system state before making changes or restarts.", ["/v1/sysinfo", "/v1/doctor", "/v1/exec"]))
        required_tools.update({"/v1/sysinfo", "/v1/doctor", "/v1/exec"})
        risks.append("System-changing actions like restart/install should be confirmed explicitly.")
    if flags["task"]:
        steps.append(_step(len(steps) + 1, "Decide whether the work should become a background task", "Long-running or recurring work should use the task queue.", ["/v1/tasks"]))
        required_tools.add("/v1/tasks")

    steps.append(_step(len(steps) + 1, "Execute the main action", "Perform the smallest useful action that advances the goal.", ["/v1/exec", "fs.edit", "browser.browse"], confirm=any(f in goal.lower() for f in ("delete", "remove", "restart", "publish", "commit"))))
    steps.append(_step(len(steps) + 1, "Verify results and record outcomes", f"Confirm success, then store important facts back into memory profile '{profile}'.", ["/v1/doctor", "memory.recall", "mem.set"]))
    required_tools.update({"/v1/exec", "fs.edit", "browser.browse", "/v1/doctor", "mem.set"})

    steps = steps[:max_steps]
    return {
        "ok": True,
        "goal": goal,
        "context": context,
        "constraints": constraints,
        "summary": f"A {len(steps)}-step plan for: {goal}",
        "suggested_memory_profile": profile,
        "required_tools": sorted(required_tools),
        "risks": risks,
        "steps": steps,
        "next_action": steps[0]["title"] if steps else "",
    }
