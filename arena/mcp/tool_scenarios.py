"""MCP tool handlers for scenario CRUD + execution.

v4.55.0: storage moved to mission filesystem
(``<ARENA_AGENT_HOME>/missions/scenario-<slug>/mission.json``).
Every mission surface (catalog, status, history, report,
schedules) now works on scenarios without any extra plumbing.

Wired into ``arena/mcp/tools.py::call_tool`` alongside
``handle_mission_tool``. Runs the scenario runtime in-process
so template resolution + tool dispatch happen in the same
Python interpreter as the bridge (no HTTP round-trip per step).

Recursion depth is capped to prevent infinite scenario→scenario
loops.
"""
from __future__ import annotations

import json
import threading
from typing import Any, Callable

from arena.mcp.tool_utils import text_content
from arena.scenarios import (
    InvalidScenario,
    ScenarioMissionStore,
    ScenarioNotFound,
    build_scenarios_runtime,
)


_MAX_RECURSION_DEPTH = 4
_recursion_depth = threading.local()


def _get_depth() -> int:
    return getattr(_recursion_depth, "value", 0)


def _incr_depth() -> None:
    _recursion_depth.value = _get_depth() + 1


def _decr_depth() -> None:
    _recursion_depth.value = max(0, _get_depth() - 1)


def _text_ok(data: dict[str, Any]) -> dict[str, Any]:
    return text_content(json.dumps(data, ensure_ascii=False))


def _text_err(msg: str, *, status: int = 500) -> dict[str, Any]:
    return text_content(json.dumps({"ok": False, "error": msg, "status": status}, ensure_ascii=False))


def _build_runtime(call_tool: Callable[[str, dict[str, Any]], dict[str, Any]]):
    def dispatch(tool: str, args: dict[str, Any]) -> dict[str, Any]:
        if tool.startswith("scenario."):
            if _get_depth() >= _MAX_RECURSION_DEPTH:
                return {"ok": False, "error": f"scenario recursion depth exceeded ({_MAX_RECURSION_DEPTH})"}
        _incr_depth()
        try:
            raw = call_tool(tool, args)
        finally:
            _decr_depth()
        content = (raw or {}).get("content") or []
        if content and isinstance(content, list):
            first = content[0] if content else {}
            text = first.get("text", "") if isinstance(first, dict) else ""
            try:
                return json.loads(text) if text else {"ok": True}
            except Exception:
                return {"ok": not bool(raw.get("isError")), "text": text}
        return raw or {"ok": True}
    return build_scenarios_runtime(dispatch)


def handle_scenario_tool(name: str, args: dict[str, Any], *, ctx) -> dict[str, Any] | None:
    """Dispatch ``scenario.*`` tool calls.

    Returns ``None`` if the tool name is not scenario-scoped so
    the outer dispatcher falls through to the next handler.
    """
    if not name.startswith("scenario."):
        return None

    call_tool = getattr(ctx, "call_tool", None)
    if not callable(call_tool):
        call_tool = lambda _t, _a: {"ok": False, "error": "no call_tool on ctx"}

    runtime = _build_runtime(call_tool)
    storage: ScenarioMissionStore = runtime.storage

    try:
        if name == "scenario.list":
            return _text_ok({"ok": True, "scenarios": storage.list()})

        if name == "scenario.get":
            scenario_name = str(args.get("name", "") or "").strip()
            if not scenario_name:
                return _text_err("`name` is required", status=400)
            got = storage.get(scenario_name)
            return _text_ok({
                "ok": True,
                "name": got["name"],
                "mission_id": got["mission_id"],
                "source": got["source"],
                "yaml": got["source"],  # legacy alias
                "doc": got["doc"],
                "path": got["path"],
            })

        if name == "scenario.save":
            scenario_name = str(args.get("name", "") or "").strip()
            source_text = str(args.get("source", "") or args.get("yaml", "") or "")
            if not scenario_name:
                return _text_err("`name` is required", status=400)
            if not source_text:
                return _text_err("`source` (or legacy `yaml`) is required", status=400)
            overwrite = bool(args.get("overwrite", True))
            saved = storage.save(scenario_name, source_text, overwrite=overwrite)
            return _text_ok({"ok": True, **saved})

        if name == "scenario.delete":
            scenario_name = str(args.get("name", "") or "").strip()
            if not scenario_name:
                return _text_err("`name` is required", status=400)
            return _text_ok({"ok": True, **storage.delete(scenario_name)})

        if name == "scenario.history":
            scenario_name = str(args.get("name", "") or "").strip()
            if not scenario_name:
                return _text_err("`name` is required", status=400)
            return _text_ok({
                "ok": True,
                "name": scenario_name,
                "runs": storage.load_history(scenario_name),
            })

        if name == "scenario.preview":
            scenario_name = str(args.get("name", "") or "").strip()
            if not scenario_name:
                return _text_err("`name` is required", status=400)
            return _text_ok(runtime.preview(scenario_name))

        if name == "scenario.run":
            scenario_name = str(args.get("name", "") or "").strip()
            if not scenario_name:
                return _text_err("`name` is required", status=400)
            approved = bool(args.get("approve", True))
            dry_run = bool(args.get("dry_run", False))
            run = runtime.run(scenario_name, approved=approved, dry_run=dry_run)
            return _text_ok(run.to_dict())

    except ScenarioNotFound as exc:
        return _text_err(f"scenario not found: {exc}", status=404)
    except InvalidScenario as exc:
        return _text_err(f"invalid scenario: {exc}", status=400)
    except Exception as exc:  # pragma: no cover -- catch-all
        return _text_err(f"{type(exc).__name__}: {exc}", status=500)

    return None


__all__ = ["handle_scenario_tool"]
