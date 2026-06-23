"""Mission template listing, composition, creation, and run helpers."""
from __future__ import annotations

import datetime as dt
import json
import os
import re
import subprocess
import sys
import uuid
from pathlib import Path
from typing import Any, Callable

from arena.resources.mission_state import infer_rerun_step
from arena.missions_cli.templates import TEMPLATES_DATA

_TEMPLATE_HINTS = {
    "browser-real-user": ("browser", "site", "page", "form", "web"),
    "tabs-game": ("game", "tabs", "steam", "level"),
    "mcp-integration": ("mcp", "tool", "integration"),
    "recovery-drill": ("recovery", "restore", "new chat"),
    "code-tdd": ("code", "repo", "test", "bug", "refactor", "implement"),
    "lan-service": ("lan", "local network", "port", "service", "scan"),
}


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")



def _slug(text: str) -> str:
    return re.sub(r"[^a-zA-Z0-9._-]+", "-", str(text or "").strip()).strip("-").lower() or "mission"



def infer_mission_template(goal: str, context: str = "") -> str:
    text = f"{goal} {context}".lower()
    for template_id, hints in _TEMPLATE_HINTS.items():
        if any(hint in text for hint in hints):
            return template_id
    return "cli-agent-core"



def list_mission_templates() -> dict[str, Any]:
    templates = []
    for template_id, data in sorted(TEMPLATES_DATA.items()):
        templates.append({"id": template_id, "title": data.get("title", ""), "goal": data.get("goal", ""), "step_count": len(data.get("steps", [])), "steps": list(data.get("steps", []))})
    return {"ok": True, "count": len(templates), "templates": templates}



def compose_mission_draft(*, goal: str, context: str = "", constraints: list[str] | None = None, max_steps: int = 8, memory_profile: str | None = None, title: str = "", template: str = "", build_plan: Callable[..., dict[str, Any]], plan: dict[str, Any] | None = None) -> dict[str, Any]:
    goal = str(goal or "").strip()
    if not goal:
        return {"ok": False, "error": "missing goal", "status": 400}
    template_id = template if template in TEMPLATES_DATA else infer_mission_template(goal, context)
    template_data = TEMPLATES_DATA.get(template_id, {})
    plan = plan or build_plan(goal=goal, context=context, constraints=constraints or [], max_steps=max_steps, memory_profile=memory_profile)
    draft = {
        "spec_version": 1,
        "title": title or template_data.get("title") or goal[:80],
        "goal": goal,
        "context": context,
        "constraints": constraints or [],
        "template": template_id,
        "template_goal": template_data.get("goal", ""),
        "template_steps": list(template_data.get("steps", [])),
        "planner_steps": list(plan.get("steps", [])),
        "required_tools": list(plan.get("required_tools", [])),
        "risks": list(plan.get("risks", [])),
        "suggested_memory_profile": plan.get("suggested_memory_profile", memory_profile or "default"),
    }
    return {"ok": True, "draft": draft, "plan": plan, "template_data": {"id": template_id, **template_data}}



def create_mission_from_draft(*, missions_dir: Path, draft: dict[str, Any], mission_id: str = "", overwrite: bool = False) -> dict[str, Any]:
    title = str(draft.get("title", "") or draft.get("goal", "") or "mission")
    mid = mission_id or dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + _slug(title) + "-" + uuid.uuid4().hex[:6]
    path = missions_dir / mid
    if path.exists() and not overwrite:
        return {"ok": False, "error": f"mission already exists: {mid}", "status": 409}
    lineage = dict(draft.get("lineage") or {}) if isinstance(draft.get("lineage"), dict) else {}
    if lineage and not lineage.get("root_mission_id"):
        lineage["root_mission_id"] = lineage.get("parent_mission_id")
    (path / "artifacts").mkdir(parents=True, exist_ok=True)
    (path / "logs").mkdir(exist_ok=True)
    mission = {"id": mid, "title": title, "created_at": _now(), "state": "planned", "draft": draft, "template": draft.get("template", "cli-agent-core"), "lineage": lineage, "runs": []}
    (path / "mission.json").write_text(json.dumps(mission, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    lines = [f"# Mission: {title}", "", f"ID: `{mid}`", f"Template: `{draft.get('template','')}`", f"Memory profile: `{draft.get('suggested_memory_profile','default')}`"]
    if lineage:
        lines += [f"Parent mission: `{lineage.get('parent_mission_id') or ''}`", f"Root mission: `{lineage.get('root_mission_id') or ''}`", f"Origin: `{lineage.get('origin') or ''}`"]
    lines += ["", "## Goal", draft.get("goal", ""), "", "## Planner steps"]
    lines += [f"- [ ] {step.get('title','')}: {step.get('reason','')}" for step in draft.get("planner_steps", [])]
    if draft.get("template_steps"):
        lines += ["", "## Template steps"] + [f"- [ ] {step}" for step in draft.get("template_steps", [])]
    (path / "PLAN.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {"ok": True, "mission_id": mid, "path": str(path), "mission": mission}



def run_mission(*, root_agent: Path, mission_id: str, step: int | None = None, timeout: int = 180, subprocess_kwargs: Callable[[], dict[str, Any]]) -> dict[str, Any]:
    if not str(mission_id or "").strip():
        return {"ok": False, "error": "missing mission_id", "status": 400}
    script = root_agent / "scripts" / "mission_manager.py"
    cmd = [sys.executable, str(script), "run", mission_id, "--timeout", str(int(timeout or 180))]
    if step is not None:
        cmd += ["--step", str(int(step))]
    env = {**os.environ, "ARENA_AGENT_HOME": str(root_agent)}
    cp = subprocess.run(cmd, cwd=str(root_agent), env=env, capture_output=True, text=True, timeout=int(timeout or 180) + 60, **subprocess_kwargs())
    return {"ok": cp.returncode == 0, "mission_id": mission_id, "step": step, "exit_code": cp.returncode, "stdout": cp.stdout[-12000:], "stderr": cp.stderr[-8000:]}


def rerun_mission(*, root_agent: Path, missions_dir: Path, mission_id: str, failed_only: bool = False, step: int | None = None, timeout: int = 180, subprocess_kwargs: Callable[[], dict[str, Any]]) -> dict[str, Any]:
    mission_id = str(mission_id or "").strip()
    if not mission_id:
        return {"ok": False, "error": "missing mission_id", "status": 400}
    inferred = infer_rerun_step(missions_dir, mission_id, failed_only=failed_only)
    if not inferred.get("ok") and step is None:
        return inferred
    effective_step = step if step is not None else inferred.get("step")
    result = run_mission(root_agent=root_agent, mission_id=mission_id, step=effective_step, timeout=timeout, subprocess_kwargs=subprocess_kwargs)
    result["rerun"] = True
    result["failed_only"] = bool(failed_only)
    return result


__all__ = ["compose_mission_draft", "create_mission_from_draft", "infer_mission_template", "list_mission_templates", "rerun_mission", "run_mission"]
