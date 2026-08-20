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
from typing import Any, Callable, cast

from arena.mcp.tool_utils import text_content
from arena.scenarios import (
    InvalidScenario,
    ScenarioMissionStore,
    ScenarioNotFound,
    build_scenarios_runtime,
    flight_records as _flight_records,
    promotion as _promotion,
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

    def _no_call_tool(_tool: str, _args: dict[str, Any]) -> dict[str, Any]:
        return {"ok": False, "error": "no call_tool on ctx"}

    # Rebinding the same name for the fallback made the union of the two
    # shapes -- an untyped attribute and a 2-arg closure -- the argument type.
    ctx_call_tool = getattr(ctx, "call_tool", None)
    call_tool: Callable[[str, dict[str, Any]], dict[str, Any]] = _no_call_tool
    if callable(ctx_call_tool):
        # `ctx` is untyped, so the attribute arrives as a bare callable; the
        # cast records the contract every scenario handler relies on.
        call_tool = cast("Callable[[str, dict[str, Any]], dict[str, Any]]", ctx_call_tool)

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

        if name == "scenario.promote_from_run":
            scenario_name = str(args.get("name", "") or "").strip()
            run = args.get("run")
            if not scenario_name:
                return _text_err("`name` is required", status=400)
            if not isinstance(run, dict):
                return _text_err("`run` object is required", status=400)
            out = _promotion.promote_from_run(
                run, name=scenario_name, overwrite=bool(args.get("overwrite", True)),
                title=str(args.get("title") or "") or None,
                description=str(args.get("description") or "") or None,
                storage=storage,
            )
            return _text_ok(out)

        if name == "scenario.promote_from_history":
            source = str(args.get("source") or args.get("scenario") or "").strip()
            scenario_name = str(args.get("name", "") or "").strip()
            if not source:
                return _text_err("`source` (or `scenario`) is required", status=400)
            if not scenario_name:
                return _text_err("`name` is required", status=400)
            out = _promotion.promote_from_history(
                source, name=scenario_name, index=int(args.get("index", -1)),
                overwrite=bool(args.get("overwrite", True)),
                title=str(args.get("title") or "") or None,
                description=str(args.get("description") or "") or None,
                storage=storage,
            )
            return _text_ok(out)

        if name == "scenario.record":
            scenario_name = str(args.get("name", "") or "").strip()
            if not scenario_name:
                return _text_err("`name` is required", status=400)
            out = _flight_records.create_record(
                scenario_name,
                title=str(args.get("title") or ""),
                status=str(args.get("status") or "observed"),
                outcome=str(args.get("outcome") or ""),
                boundary=args.get("boundary"),
                summary=args.get("summary"),
                observations=args.get("observations"),
                artifacts=args.get("artifacts"),
                commands=args.get("commands"),
                worked=args.get("worked"),
                not_worked=args.get("not_worked"),
                next_steps=args.get("next_steps"),
                data=args.get("data"),
                risk=str(args.get("risk") or ""),
                tags=args.get("tags"),
                storage=storage,
            )
            compact = {k: v for k, v in out.items() if k != "record"}
            compact["record"] = out["record"]
            return _text_ok(compact)

        if name == "scenario.records":
            scenario_name = str(args.get("name", "") or "").strip()
            if not scenario_name:
                return _text_err("`name` is required", status=400)
            return _text_ok(_flight_records.list_records(scenario_name, storage=storage))

        if name == "scenario.flight_report":
            scenario_name = str(args.get("name", "") or "").strip()
            if not scenario_name:
                return _text_err("`name` is required", status=400)
            return _text_ok(_flight_records.get_report(
                scenario_name,
                record_id=str(args.get("record_id") or ""),
                latest=bool(args.get("latest", True)),
                storage=storage,
            ))

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
    except ValueError as exc:
        # Promotion rejects unpromotable runs (empty or dry-run) with
        # ValueError. That is a bad request, not a server fault, and the
        # catch-all below would report it as 500.
        return _text_err(str(exc), status=400)
    except Exception as exc:  # pragma: no cover -- catch-all
        return _text_err(f"{type(exc).__name__}: {exc}", status=500)

    return None


__all__ = ["handle_scenario_tool"]
