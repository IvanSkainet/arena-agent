"""Scenario execution runtime.

Given a scenario document and a callable that dispatches an
Arena MCP tool (``dispatch(tool, arguments) -> dict``), the
runtime runs steps in order, interpolates
``{{ steps.<id>.result.<path> }}`` / ``{{ env.VAR }}`` /
``{{ now }}`` template expressions, and collects per-step
results plus a final ``return`` value.

Design notes
------------
* Template resolution is intentionally minimal (no full Jinja
  runtime) — we want the substitution surface tiny and
  auditable. Only three source namespaces:
  ``steps.<id>.result[.field.subfield]``, ``env.<VAR>``, ``now``.
* Missing template targets do NOT explode; they render as the
  empty string (Bash-like). Rationale: an on-error `continue`
  chain often expects downstream steps to handle the missing
  field explicitly.
* ``derive_scenario_risk`` reads every step's ``tool`` and
  returns the max risk. This is the value the extension policy
  layer surfaces via ``classify_tool_risk("scenario.run")``.
* All step results are wrapped into a normalised shape:
  ``{"ok": bool, "tool": str, "result": Any, "error": str|None,
    "duration_ms": int}`` — makes downstream template access
  predictable.
"""
from __future__ import annotations

import copy
import json
import os
import re
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from arena.extension_bridge.policy import classify_tool_risk
from arena.scenarios.storage import (
    InvalidScenario,
    ScenarioNotFound,
    ScenariosStorage,
    parse_scenario_source,
)


RISK_ORDER = {"safe": 0, "medium": 1, "dangerous": 2, "unknown": 1}
_TEMPLATE_RE = re.compile(r"\{\{\s*([^}]+?)\s*\}\}")


@dataclass
class ScenarioStepResult:
    id: str
    tool: str
    ok: bool
    result: Any
    error: str | None
    duration_ms: int
    arguments: dict[str, Any] = field(default_factory=dict)
    returned: Any = None  # for `return:` steps


@dataclass
class ScenarioRunResult:
    ok: bool
    name: str
    started_at: str
    finished_at: str
    duration_ms: int
    steps: list[ScenarioStepResult]
    final: Any
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "name": self.name,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "duration_ms": self.duration_ms,
            "steps": [
                {
                    "id": s.id, "tool": s.tool, "ok": s.ok,
                    "result": s.result, "error": s.error,
                    "duration_ms": s.duration_ms,
                    "arguments": s.arguments,
                    "returned": s.returned,
                } for s in self.steps
            ],
            "final": self.final,
            "error": self.error,
        }


def derive_scenario_risk(doc: dict[str, Any]) -> str:
    """Return the max risk among the scenario's steps' tools.

    Empty scenario → ``safe``. Any tool classified as ``unknown``
    counts as ``medium`` (approval required) since we cannot
    prove it's benign.
    """
    max_score = 0
    for step in doc.get("steps") or []:
        tool = str(step.get("tool") or "").strip()
        if not tool:
            continue
        risk = classify_tool_risk(tool)
        score = RISK_ORDER.get(risk, 1)
        if score > max_score:
            max_score = score
    for name, score in RISK_ORDER.items():
        if score == max_score and name != "unknown":
            return name
    return "safe"


def _resolve_path(root: Any, path: str) -> Any:
    """Walk a dotted path through nested dicts/lists.

    Missing paths return ``""`` (per module docstring).
    """
    cur: Any = root
    for part in path.split("."):
        if part == "":
            continue
        if isinstance(cur, dict):
            cur = cur.get(part, "")
        elif isinstance(cur, list):
            try:
                cur = cur[int(part)]
            except (ValueError, IndexError):
                return ""
        else:
            return ""
    return cur


def _stringify(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (str, int, float, bool)):
        return str(value) if not isinstance(value, bool) else ("true" if value else "false")
    try:
        return json.dumps(value, ensure_ascii=False)
    except Exception:
        return str(value)


def render_template(text: str, context: dict[str, Any]) -> str:
    """Substitute ``{{ … }}`` expressions in a string.

    Supported forms:
      * ``steps.<id>.result[.<path>]`` — value of a prior step's result
      * ``steps.<id>.returned`` — value returned by a `return:` step
      * ``env.<VAR>`` — process env
      * ``now`` — ISO-8601 timestamp
    """
    if not isinstance(text, str) or "{{" not in text:
        return text  # type: ignore[return-value]

    def _sub(match: re.Match[str]) -> str:
        expr = match.group(1).strip()
        if expr == "now":
            return time.strftime("%Y-%m-%dT%H:%M:%S")
        if expr.startswith("env."):
            return os.environ.get(expr[4:], "")
        if expr.startswith("steps."):
            rest = expr[len("steps."):]
            # rest is like `myid.result.foo.bar` or `myid.returned`
            parts = rest.split(".", 1)
            step_id = parts[0]
            step = (context.get("steps") or {}).get(step_id)
            if not step:
                return ""
            if len(parts) == 1:
                return _stringify(step)
            tail = parts[1]
            if tail == "returned":
                return _stringify(step.get("returned"))
            if tail == "result":
                return _stringify(step.get("result"))
            if tail.startswith("result."):
                return _stringify(_resolve_path(step.get("result"), tail[len("result."):]))
            return _stringify(_resolve_path(step, tail))
        return match.group(0)

    return _TEMPLATE_RE.sub(_sub, text)


def _render_deep(value: Any, context: dict[str, Any]) -> Any:
    if isinstance(value, str):
        return render_template(value, context)
    if isinstance(value, list):
        return [_render_deep(v, context) for v in value]
    if isinstance(value, dict):
        return {k: _render_deep(v, context) for k, v in value.items()}
    return value


class ScenariosRuntime:
    """Loads scenarios from storage and runs them via a tool dispatcher."""

    def __init__(
        self,
        storage: ScenariosStorage,
        dispatch: Callable[[str, dict[str, Any]], dict[str, Any]],
    ) -> None:
        self._storage = storage
        self._dispatch = dispatch

    @property
    def storage(self) -> ScenariosStorage:
        return self._storage

    def preview(self, name: str) -> dict[str, Any]:
        """Read a scenario and return its risk + step plan."""
        got = self._storage.get(name)
        doc = got["doc"]
        risk = derive_scenario_risk(doc)
        return {
            "ok": True,
            "name": got["name"],
            "risk": risk,
            "step_count": len(doc.get("steps") or []),
            "tools": [str(s.get("tool") or "") for s in doc.get("steps") or [] if s.get("tool")],
            "path": got["path"],
        }

    def run(self, name: str, *, approved: bool = False, dry_run: bool = False) -> ScenarioRunResult:
        got = self._storage.get(name)
        doc = got["doc"]
        risk = derive_scenario_risk(doc)
        started = time.time()
        started_iso = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(started))

        # Policy gate: medium/dangerous scenarios need explicit
        # approval (matches extension /execute semantics).
        if risk != "safe" and not approved:
            return ScenarioRunResult(
                ok=False, name=got["name"],
                started_at=started_iso, finished_at=started_iso,
                duration_ms=0, steps=[], final=None,
                error=f"approval required (derived risk={risk})",
            )

        context: dict[str, Any] = {"steps": {}}
        step_results: list[ScenarioStepResult] = []
        overall_ok = True

        for spec in doc.get("steps") or []:
            step_id = str(spec.get("id"))
            step_started = time.time()
            if "return" in spec and not spec.get("tool"):
                # Pure return step: evaluate template and record.
                returned = _render_deep(copy.deepcopy(spec["return"]), context)
                sr = ScenarioStepResult(
                    id=step_id, tool="",
                    ok=True, result=None, error=None,
                    duration_ms=int((time.time() - step_started) * 1000),
                    arguments={}, returned=returned,
                )
                context["steps"][step_id] = {"tool": "", "result": None, "returned": returned, "ok": True}
                step_results.append(sr)
                continue

            tool = str(spec.get("tool") or "").strip()
            raw_args = copy.deepcopy(spec.get("arguments") or {})
            args = _render_deep(raw_args, context)
            if dry_run:
                sr = ScenarioStepResult(
                    id=step_id, tool=tool, ok=True,
                    result={"dry_run": True, "arguments": args},
                    error=None,
                    duration_ms=int((time.time() - step_started) * 1000),
                    arguments=args,
                )
                context["steps"][step_id] = {"tool": tool, "result": sr.result, "returned": None, "ok": True}
                step_results.append(sr)
                continue

            try:
                raw = self._dispatch(tool, args)
                result = raw if isinstance(raw, dict) else {"value": raw}
                ok = bool(result.get("ok", True)) and not result.get("isError")
                error = None if ok else str(result.get("error") or "step failed")
            except Exception as exc:
                ok = False
                result = {"ok": False, "error": str(exc)}
                error = str(exc)

            sr = ScenarioStepResult(
                id=step_id, tool=tool, ok=ok, result=result, error=error,
                duration_ms=int((time.time() - step_started) * 1000),
                arguments=args,
            )
            context["steps"][step_id] = {"tool": tool, "result": result, "returned": None, "ok": ok}
            step_results.append(sr)

            if not ok and not spec.get("continue_on_error"):
                overall_ok = False
                break

        # Final: if last step had `return`, use it; else surface
        # a summary of the tail step's result.
        final: Any = None
        if step_results:
            tail = step_results[-1]
            final = tail.returned if tail.returned is not None else tail.result

        finished = time.time()
        finished_iso = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(finished))
        run = ScenarioRunResult(
            ok=overall_ok, name=got["name"],
            started_at=started_iso, finished_at=finished_iso,
            duration_ms=int((finished - started) * 1000),
            steps=step_results, final=final,
        )
        self._storage.append_history(got["name"], run.to_dict())
        return run


def build_scenarios_runtime(
    dispatch: Callable[[str, dict[str, Any]], dict[str, Any]],
    *,
    storage: ScenariosStorage | None = None,
) -> ScenariosRuntime:
    return ScenariosRuntime(storage or ScenariosStorage(), dispatch)


__all__ = [
    "ScenariosRuntime",
    "ScenarioRunResult",
    "ScenarioStepResult",
    "build_scenarios_runtime",
    "derive_scenario_risk",
    "render_template",
    "RISK_ORDER",
    "parse_scenario_source",
    "InvalidScenario",
    "ScenarioNotFound",
]
