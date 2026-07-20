"""MCP tool handlers for scenario CRUD + execution.

Wired into ``arena/mcp/tools.py::call_tool`` alongside
``handle_mission_tool`` etc. Runs directly against
:mod:`arena.scenarios.runtime` — no HTTP hop through the bridge
loopback — so scenarios don't pay the network cost on every
step and step results avoid double JSON serialisation.

Recursion is intentional: ``scenario.run`` gets the same
``call_tool`` callable that dispatched it, so a scenario can
invoke another scenario as one of its steps. Depth protection
is enforced via a thread-local counter to avoid infinite loops.
"""
from __future__ import annotations

import json
import threading
from typing import Any, Callable

from arena.mcp.tool_utils import text_content
from arena.scenarios import (
    InvalidScenario,
    ScenarioNotFound,
    ScenariosRuntime,
    ScenariosStorage,
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


def _build_runtime(call_tool: Callable[[str, dict[str, Any]], dict[str, Any]]) -> ScenariosRuntime:
    def dispatch(tool: str, args: dict[str, Any]) -> dict[str, Any]:
        if tool.startswith("scenario."):
            # Guard recursion depth for nested scenario.run.
            if _get_depth() >= _MAX_RECURSION_DEPTH:
                return {"ok": False, "error": f"scenario recursion depth exceeded ({_MAX_RECURSION_DEPTH})"}
        _incr_depth()
        try:
            raw = call_tool(tool, args)
        finally:
            _decr_depth()
        # `call_tool` returns MCP content shape; distill to a
        # plain dict scenarios can consume. The mission tools
        # wrap results as text_content -> parse it back if it
        # looks like JSON, otherwise pass the raw text through.
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
    the outer dispatcher can fall through to the next handler.
    """
    if not name.startswith("scenario."):
        return None

    # ctx.call_tool is the parent dispatcher that lets us call
    # any Arena tool from within a scenario step.
    call_tool = getattr(ctx, "call_tool", None)
    if not callable(call_tool):
        # Fallback so unit tests can inject a bare ctx without
        # the full runtime; scenarios that call other tools will
        # then fail per-step but scenario CRUD still works.
        call_tool = lambda _t, _a: {"ok": False, "error": "no call_tool on ctx"}

    runtime = _build_runtime(call_tool)
    storage: ScenariosStorage = runtime.storage

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
                # `source` is the canonical JSON dump; `yaml` alias
                # kept for tools/UIs that historically read that key.
                "source": got["source"],
                "yaml": got["source"],
                "doc": got["doc"],
                "path": got["path"],
            })

        if name == "scenario.save":
            scenario_name = str(args.get("name", "") or "").strip()
            # Accept both `source` (canonical) and `yaml` (legacy).
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
            approved = bool(args.get("approve", True))  # tool caller opted in
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
