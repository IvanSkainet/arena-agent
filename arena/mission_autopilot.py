"""Mission Autopilot: bounded tool-chain execution with flight records.

This is intentionally small and deterministic.  It does not pretend to be a
planner/LLM; it turns a goal plus explicit or default steps into a persisted
run, executes those steps through the bridge MCP surface, stores progress as
JSON, and optionally emits a scenario flight record.
"""
from __future__ import annotations

import datetime as dt
import json
import re
import urllib.request
import uuid
from pathlib import Path
from typing import Any


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def _slug(value: str, fallback: str = "autopilot") -> str:
    s = re.sub(r"[^a-zA-Z0-9._-]+", "-", str(value or "").strip()).strip("-").lower()
    return s[:70] or fallback


def _home() -> Path:
    import os
    return Path(os.environ.get("ARENA_AGENT_HOME", str(Path.home() / "arena-bridge"))).expanduser()


def _runs_dir() -> Path:
    p = _home() / "autopilot" / "runs"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _run_path(run_id: str) -> Path:
    return _runs_dir() / f"{_slug(run_id)}.json"


def _default_steps() -> list[dict[str, Any]]:
    return [
        {"id": "ship_preflight", "tool": "ship.preflight", "arguments": {}},
        {"id": "workbench", "tool": "workbench.status", "arguments": {}},
        {"id": "desktop", "tool": "desktop.windows", "arguments": {"include_displays": True}},
        {"id": "mobile", "tool": "mobile.preflight", "arguments": {}},
        {"id": "scenarios", "tool": "scenario.list", "arguments": {}},
    ]


def _mcp_call(port: int, token: str, tool: str, arguments: dict[str, Any], timeout: int) -> dict[str, Any]:
    payload = {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": tool, "arguments": arguments or {}}}
    req = urllib.request.Request(
        f"http://127.0.0.1:{int(port)}/mcp",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=max(1, int(timeout))) as resp:  # nosec B310 -- loopback only
        outer = json.loads(resp.read().decode("utf-8", "replace"))
    content = (outer.get("result") or {}).get("content") or []
    text = content[0].get("text", "") if content and isinstance(content[0], dict) else ""
    try:
        parsed = json.loads(text) if text else {}
    except Exception:
        parsed = {"ok": not bool((outer.get("result") or {}).get("isError")), "text": text}
    parsed.setdefault("_raw_is_error", bool((outer.get("result") or {}).get("isError")))
    return parsed


def _save(run: dict[str, Any]) -> None:
    _run_path(run["run_id"]).write_text(json.dumps(run, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _load(run_id: str) -> dict[str, Any]:
    p = _run_path(run_id)
    if not p.exists():
        raise FileNotFoundError(run_id)
    return json.loads(p.read_text(encoding="utf-8"))


def list_runs(limit: int = 20) -> dict[str, Any]:
    runs = []
    for p in sorted(_runs_dir().glob("*.json"), key=lambda x: x.stat().st_mtime, reverse=True)[: max(1, int(limit or 20))]:
        try:
            obj = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        runs.append({k: obj.get(k) for k in ("run_id", "goal", "status", "outcome", "created_at", "finished_at", "scenario")})
    return {"ok": True, "count": len(runs), "runs": runs}


def status(run_id: str) -> dict[str, Any]:
    run = _load(run_id)
    return {"ok": True, **{k: run.get(k) for k in ("run_id", "goal", "status", "outcome", "created_at", "finished_at", "scenario")}, "step_count": len(run.get("steps") or []), "path": str(_run_path(run_id))}


def report(run_id: str) -> dict[str, Any]:
    run = _load(run_id)
    lines = [f"# Autopilot run {run_id}", "", f"Goal: {run.get('goal')}", f"Status: `{run.get('status')}`", f"Outcome: {run.get('outcome','')}", "", "## Steps"]
    for idx, step in enumerate(run.get("steps") or [], start=1):
        lines.append(f"{idx}. `{step.get('tool')}` ok={step.get('ok')} id={step.get('id')}")
    md = "\n".join(lines) + "\n"
    md_path = _run_path(run_id).with_suffix(".md")
    md_path.write_text(md, encoding="utf-8")
    return {"ok": True, "run": run, "markdown": md, "json_path": str(_run_path(run_id)), "markdown_path": str(md_path)}


def start(
    *,
    goal: str,
    steps: list[dict[str, Any]] | None,
    constraints: list[str] | None,
    max_steps: int,
    timeout_per_step: int,
    create_record: bool,
    scenario_name: str,
    port: int,
    token: str,
) -> dict[str, Any]:
    if not goal:
        return {"ok": False, "error": "goal is required"}
    step_specs = list(steps or _default_steps())[: max(1, min(int(max_steps or 12), 60))]
    run_id = f"{dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:8]}"
    scenario = scenario_name or f"autopilot-{_slug(goal)}"
    run: dict[str, Any] = {
        "ok": True,
        "run_id": run_id,
        "goal": goal,
        "constraints": constraints or [],
        "scenario": scenario,
        "status": "running",
        "created_at": _now(),
        "steps": [],
    }
    _save(run)
    for spec in step_specs:
        sid = str(spec.get("id") or f"step{len(run['steps'])+1}")
        tool = str(spec.get("tool") or "").strip()
        args = spec.get("arguments") or {}
        if not tool:
            step = {"id": sid, "ok": False, "error": "missing tool"}
        else:
            try:
                result = _mcp_call(port, token, tool, args, int(spec.get("timeout", timeout_per_step) or timeout_per_step))
                step = {"id": sid, "tool": tool, "arguments": args, "ok": (not result.get("_raw_is_error") and result.get("ok", True) is not False), "result": result}
            except Exception as exc:
                step = {"id": sid, "tool": tool, "arguments": args, "ok": False, "error": f"{type(exc).__name__}: {exc}"}
        run["steps"].append(step)
        _save(run)
        if not step.get("ok") and not bool(spec.get("continue_on_error", True)):
            break
    failed = [s for s in run["steps"] if not s.get("ok")]
    run["status"] = "partial" if failed else "nominal"
    run["outcome"] = "completed with failures" if failed else "completed"
    run["finished_at"] = _now()
    _save(run)

    # Persist a scenario shell + flight record so the result lands in the normal scenario surface.
    if create_record:
        scenario_doc = {
            "name": scenario,
            "title": f"Autopilot: {goal[:80]}",
            "description": "Autopilot-generated scenario shell and flight record.",
            "steps": [{"id": "summary", "tool": "exec.echo", "arguments": {"text": goal}}],
        }
        try:
            _mcp_call(port, token, "scenario.save", {"name": scenario, "source": json.dumps(scenario_doc, ensure_ascii=False), "overwrite": True}, timeout_per_step)
            _mcp_call(port, token, "scenario.record", {
                "name": scenario,
                "title": f"Autopilot flight record: {goal[:80]}",
                "status": run["status"],
                "outcome": run["outcome"],
                "boundary": constraints or [],
                "summary": f"Autopilot executed {len(run['steps'])} steps for goal: {goal}",
                "observations": [{"title": s.get("id"), "tool": s.get("tool"), "ok": s.get("ok")} for s in run["steps"]],
                "not_worked": failed,
                "data": {"run_id": run_id, "json_path": str(_run_path(run_id))},
            }, timeout_per_step)
        except Exception as exc:
            run["record_error"] = f"{type(exc).__name__}: {exc}"
            _save(run)
    return {"ok": True, "run_id": run_id, "status": run["status"], "outcome": run["outcome"], "scenario": scenario, "step_count": len(run["steps"]), "path": str(_run_path(run_id))}


__all__ = ["list_runs", "report", "start", "status"]
