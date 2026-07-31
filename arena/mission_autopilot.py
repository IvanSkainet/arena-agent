"""Mission Autopilot: bounded tool-chain execution with flight records.

This is intentionally small and deterministic.  It does not pretend to be a
planner/LLM; it turns a goal plus explicit or default steps into a persisted
run, executes those steps through the bridge MCP surface, stores progress as
JSON, and optionally emits a scenario flight record.

v4.149.0 additions:
- ``cancel`` — mark a running run as cancelled.
- ``step`` — execute one step in an existing run (append or re-run).
- ``artifacts`` — collect artifacts/results from a run's steps.
- ``from_goal`` — goal-to-plan: map a natural-language goal to tool steps
  based on ship capabilities, then run them.

v4.150.0 additions:
- ``start_async`` — launch an autopilot run in a background thread;
  returns immediately with the run_id.
- ``cancel`` now also interrupts a background-running thread.
"""
from __future__ import annotations

import datetime as dt
import json
import re
import threading
import urllib.request
import uuid
from pathlib import Path
from typing import Any

# Background run registry: run_id → threading.Event (set = cancel requested)
_background_cancel: dict[str, threading.Event] = {}
_background_lock = threading.Lock()
_file_lock = threading.Lock()  # guards concurrent read/write of run JSON files


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


# ---------------------------------------------------------------------------
# Goal-to-plan: map natural-language goal keywords to tool steps.
# ---------------------------------------------------------------------------

_GOAL_PATTERNS: list[tuple[list[str], list[dict[str, Any]]]] = [
    (
        ["desktop", "window", "screen", "screenshot", "display"],
        [
            {"id": "desktop_windows", "tool": "desktop.windows", "arguments": {"include_displays": True}},
            {"id": "desktop_displays", "tool": "desktop.displays", "arguments": {}},
        ],
    ),
    (
        ["browser", "web", "search", "url"],
        [
            {"id": "browser_search", "tool": "browser.search", "arguments": {"query": "status"}},
        ],
    ),
    (
        ["mobile", "phone", "adb", "poco"],
        [
            {"id": "mobile_preflight", "tool": "mobile.preflight", "arguments": {}},
            {"id": "mobile_observe", "tool": "mobile.observe", "arguments": {}},
        ],
    ),
    (
        ["mumu", "emulator", "android"],
        [
            {"id": "mumu_info", "tool": "mumu.info", "arguments": {}},
            {"id": "mumu_screenshot", "tool": "mumu.screenshot", "arguments": {}},
        ],
    ),
    (
        ["code", "run", "script", "python", "exec"],
        [
            {"id": "code_run", "tool": "code.run", "arguments": {"language": "python", "code": "print('autopilot code step')"}},
        ],
    ),
    (
        ["file", "fs", "read", "write", "directory"],
        [
            {"id": "fs_list", "tool": "fs.list", "arguments": {"path": "."}},
        ],
    ),
    (
        ["scenario", "mission", "flight"],
        [
            {"id": "scenario_list", "tool": "scenario.list", "arguments": {}},
        ],
    ),
    (
        ["capability", "gap"],
        [
            {"id": "gap_list", "tool": "capability_gap.list", "arguments": {}},
        ],
    ),
    (
        ["ship", "preflight", "status", "health", "check"],
        [
            {"id": "ship_preflight", "tool": "ship.preflight", "arguments": {}},
            {"id": "ship_status", "tool": "ship.status", "arguments": {}},
        ],
    ),
]


def _plan_from_goal(goal: str) -> list[dict[str, Any]]:
    """Derive tool steps from a goal string by keyword matching.

    Returns matching steps, or a safe default checklist if no keywords match.
    """
    goal_lower = goal.lower()
    steps: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for keywords, pattern_steps in _GOAL_PATTERNS:
        if any(kw in goal_lower for kw in keywords):
            for s in pattern_steps:
                if s["id"] not in seen_ids:
                    steps.append(s)
                    seen_ids.add(s["id"])
    if not steps:
        # Fallback: full ship check
        steps = _default_steps()
    return steps


def _mcp_call(port: int, token: str, tool: str, arguments: dict[str, Any], timeout: int) -> dict[str, Any]:
    payload = {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": tool, "arguments": arguments or {}}}
    req = urllib.request.Request(
        f"http://127.0.0.1:{int(port)}/mcp",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=max(1, int(timeout))) as resp:  # nosec B310 -- loopback-only MCP dispatch to the same local bridge; nosemgrep: dynamic-urllib-use-detected -- URL is fixed to 127.0.0.1 with only the already-bound local port variable
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
    """Persist a run file, guarded by a lock to prevent concurrent-write races."""
    with _file_lock:
        _run_path(run["run_id"]).write_text(json.dumps(run, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _load(run_id: str) -> dict[str, Any]:
    """Load a run file, guarded by a lock to prevent reading mid-write."""
    with _file_lock:
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


# ---------------------------------------------------------------------------
# v4.149.0: cancel
# ---------------------------------------------------------------------------

def cancel(run_id: str) -> dict[str, Any]:
    """Mark a running autopilot run as cancelled.

    If the run is executing in a background thread (start_async), signals
    the thread to stop after the current step completes.
    """
    run = _load(run_id)
    if run.get("status") not in ("running", "paused"):
        return {"ok": False, "error": f"run is already {run.get('status')}, cannot cancel", "run_id": run_id}

    # Signal background thread if present
    with _background_lock:
        evt = _background_cancel.get(run_id)
        if evt is not None:
            evt.set()
            # Let the worker finalize state
            return {"ok": True, "run_id": run_id, "status": "cancelling", "hint": "background run will stop after current step"}

    run["status"] = "cancelled"
    run["outcome"] = "cancelled by operator"
    run["finished_at"] = _now()
    _save(run)
    return {"ok": True, "run_id": run_id, "status": "cancelled"}


# ---------------------------------------------------------------------------
# v4.149.0: step — execute one step in an existing run
# ---------------------------------------------------------------------------

def step(
    *,
    run_id: str,
    tool: str,
    arguments: dict[str, Any] | None = None,
    step_id: str = "",
    timeout: int = 60,
    port: int = 8765,
    token: str = "",
) -> dict[str, Any]:
    """Execute one step inside an existing autopilot run and persist it.

    The run does not need to be in 'running' state — this also works for
    completed/partial runs, effectively appending a follow-up step.
    """
    run = _load(run_id)
    sid = step_id or f"step{len(run.get('steps', [])) + 1}"
    if not tool:
        return {"ok": False, "error": "tool is required", "run_id": run_id}
    try:
        result = _mcp_call(port, token, tool, arguments or {}, timeout)
        step_rec = {"id": sid, "tool": tool, "arguments": arguments or {}, "ok": (not result.get("_raw_is_error") and result.get("ok", True) is not False), "result": result, "executed_at": _now()}
    except Exception as exc:
        step_rec = {"id": sid, "tool": tool, "arguments": arguments or {}, "ok": False, "error": f"{type(exc).__name__}: {exc}", "executed_at": _now()}
    run.setdefault("steps", []).append(step_rec)
    # Re-evaluate overall status
    failed = [s for s in run["steps"] if not s.get("ok")]
    run["status"] = "partial" if failed else "nominal"
    run["outcome"] = "in progress" if run.get("status") == "running" else ("completed with failures" if failed else "completed")
    run["updated_at"] = _now()
    _save(run)
    return {"ok": True, "run_id": run_id, "step": step_rec, "step_count": len(run["steps"]), "status": run["status"]}


# ---------------------------------------------------------------------------
# v4.149.0: artifacts — collect artifacts from run steps
# ---------------------------------------------------------------------------

def artifacts(run_id: str) -> dict[str, Any]:
    """Collect all artifacts (results, paths, screenshots) from a run."""
    run = _load(run_id)
    arts: list[dict[str, Any]] = []
    for s in run.get("steps") or []:
        entry: dict[str, Any] = {"step_id": s.get("id"), "tool": s.get("tool"), "ok": s.get("ok")}
        result = s.get("result") or {}
        # Collect notable keys from result
        for key in ("path", "screenshot", "file", "json_path", "markdown_path", "url", "artifacts", "text"):
            if key in result:
                entry[key] = result[key]
        if s.get("error"):
            entry["error"] = s["error"]
        arts.append(entry)
    return {
        "ok": True,
        "run_id": run_id,
        "artifact_count": len(arts),
        "artifacts": arts,
        "json_path": str(_run_path(run_id)),
    }


# ---------------------------------------------------------------------------
# v4.149.0: from_goal — plan steps from goal, then execute
# ---------------------------------------------------------------------------

def from_goal(
    *,
    goal: str,
    constraints: list[str] | None = None,
    max_steps: int = 12,
    timeout_per_step: int = 60,
    create_record: bool = True,
    scenario_name: str = "",
    port: int = 8765,
    token: str = "",
) -> dict[str, Any]:
    """Plan steps from a natural-language goal, then execute them.

    This is the planner entry-point: goal → keyword matching → tool steps → start.
    """
    if not goal:
        return {"ok": False, "error": "goal is required"}
    planned_steps = _plan_from_goal(goal)[:max(1, min(int(max_steps or 12), 60))]
    result = start(
        goal=goal,
        steps=planned_steps,
        constraints=constraints,
        max_steps=max_steps,
        timeout_per_step=timeout_per_step,
        create_record=create_record,
        scenario_name=scenario_name,
        port=port,
        token=token,
    )
    result["planned_steps"] = [{"id": s["id"], "tool": s["tool"]} for s in planned_steps]
    result["planner"] = "keyword"
    return result


def _is_cancelled(run_id: str) -> bool:
    """Check if a background cancel has been requested for this run."""
    with _background_lock:
        evt = _background_cancel.get(run_id)
    return evt is not None and evt.is_set()


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
        # v4.150.0: check for cancel between steps
        if _is_cancelled(run_id):
            run["status"] = "cancelled"
            run["outcome"] = "cancelled by operator"
            run["finished_at"] = _now()
            _save(run)
            with _background_lock:
                _background_cancel.pop(run_id, None)
            return {"ok": True, "run_id": run_id, "status": "cancelled", "outcome": "cancelled by operator", "scenario": scenario, "step_count": len(run["steps"]), "path": str(_run_path(run_id))}

        sid = str(spec.get("id") or f"step{len(run['steps'])+1}")
        tool = str(spec.get("tool") or "").strip()
        args = spec.get("arguments") or {}
        if not tool:
            step_rec = {"id": sid, "ok": False, "error": "missing tool"}
        else:
            try:
                result = _mcp_call(port, token, tool, args, int(spec.get("timeout", timeout_per_step) or timeout_per_step))
                step_rec = {"id": sid, "tool": tool, "arguments": args, "ok": (not result.get("_raw_is_error") and result.get("ok", True) is not False), "result": result}
            except Exception as exc:
                step_rec = {"id": sid, "tool": tool, "arguments": args, "ok": False, "error": f"{type(exc).__name__}: {exc}"}
        run["steps"].append(step_rec)
        _save(run)
        if not step_rec.get("ok") and not bool(spec.get("continue_on_error", True)):
            break
    failed = [s for s in run["steps"] if not s.get("ok")]
    if run["status"] != "cancelled":
        run["status"] = "partial" if failed else "nominal"
        run["outcome"] = "completed with failures" if failed else "completed"
    run["finished_at"] = _now()
    _save(run)
    # Clean up cancel event if present
    with _background_lock:
        _background_cancel.pop(run_id, None)

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


# ---------------------------------------------------------------------------
# v4.150.0: start_async — background autopilot execution
# ---------------------------------------------------------------------------

def start_async(
    *,
    goal: str,
    steps: list[dict[str, Any]] | None = None,
    constraints: list[str] | None = None,
    max_steps: int = 12,
    timeout_per_step: int = 60,
    create_record: bool = True,
    scenario_name: str = "",
    port: int = 8765,
    token: str = "",
) -> dict[str, Any]:
    """Launch an autopilot run in a background thread.

    Returns immediately with the run_id.  Use ``status(run_id)`` to poll
    progress.  Use ``cancel(run_id)`` to interrupt.
    """
    if not goal:
        return {"ok": False, "error": "goal is required"}

    # Pre-generate run_id so we can return it immediately
    run_id = f"{dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:8]}"
    scenario = scenario_name or f"autopilot-{_slug(goal)}"
    step_specs = list(steps or _default_steps())[: max(1, min(int(max_steps or 12), 60))]

    # Create initial persisted state
    run: dict[str, Any] = {
        "ok": True,
        "run_id": run_id,
        "goal": goal,
        "constraints": constraints or [],
        "scenario": scenario,
        "status": "running",
        "async": True,
        "created_at": _now(),
        "steps": [],
    }
    _save(run)

    # Register cancel event
    cancel_evt = threading.Event()
    with _background_lock:
        _background_cancel[run_id] = cancel_evt

    def _worker() -> None:
        try:
            # Re-load to get the fresh state
            r = _load(run_id)
            for spec in step_specs:
                if cancel_evt.is_set():
                    r["status"] = "cancelled"
                    r["outcome"] = "cancelled by operator"
                    r["finished_at"] = _now()
                    _save(r)
                    return

                sid = str(spec.get("id") or f"step{len(r['steps'])+1}")
                tool = str(spec.get("tool") or "").strip()
                args = spec.get("arguments") or {}
                if not tool:
                    step_rec = {"id": sid, "ok": False, "error": "missing tool"}
                else:
                    try:
                        result = _mcp_call(port, token, tool, args, int(spec.get("timeout", timeout_per_step) or timeout_per_step))
                        step_rec = {"id": sid, "tool": tool, "arguments": args, "ok": (not result.get("_raw_is_error") and result.get("ok", True) is not False), "result": result}
                    except Exception as exc:
                        step_rec = {"id": sid, "tool": tool, "arguments": args, "ok": False, "error": f"{type(exc).__name__}: {exc}"}
                r["steps"].append(step_rec)
                _save(r)
                if not step_rec.get("ok") and not bool(spec.get("continue_on_error", True)):
                    break

            failed = [s for s in r["steps"] if not s.get("ok")]
            if r["status"] != "cancelled":
                r["status"] = "partial" if failed else "nominal"
                r["outcome"] = "completed with failures" if failed else "completed"
            r["finished_at"] = _now()
            _save(r)

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
                        "status": r["status"],
                        "outcome": r["outcome"],
                        "boundary": constraints or [],
                        "summary": f"Autopilot executed {len(r['steps'])} steps for goal: {goal}",
                        "observations": [{"title": s.get("id"), "tool": s.get("tool"), "ok": s.get("ok")} for s in r["steps"]],
                        "not_worked": failed,
                        "data": {"run_id": run_id, "json_path": str(_run_path(run_id))},
                    }, timeout_per_step)
                except Exception as exc:
                    r["record_error"] = f"{type(exc).__name__}: {exc}"
                    _save(r)
        except Exception as exc:
            try:
                r2 = _load(run_id)
                r2["status"] = "error"
                r2["outcome"] = f"background worker error: {type(exc).__name__}: {exc}"
                r2["finished_at"] = _now()
                _save(r2)
            except Exception:
                pass
        finally:
            with _background_lock:
                _background_cancel.pop(run_id, None)

    t = threading.Thread(target=_worker, name=f"autopilot-{run_id}", daemon=True)
    t.start()

    return {
        "ok": True,
        "run_id": run_id,
        "status": "running",
        "async": True,
        "scenario": scenario,
        "planned_step_count": len(step_specs),
        "path": str(_run_path(run_id)),
        "hint": "Use mission.autopilot_status to poll progress, mission.autopilot_cancel to interrupt.",
    }


__all__ = ["artifacts", "cancel", "from_goal", "list_runs", "report", "start", "start_async", "status", "step"]
