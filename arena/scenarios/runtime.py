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
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from arena.extension_bridge.policy import classify_tool_risk
from arena.scenarios.storage import (
    InvalidScenario,
    ScenarioNotFound,
    parse_scenario_source,
)
from arena.scenarios.mission_bridge import ScenarioMissionStore


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
    prove it's benign. As of v4.54.1 a ``wait_for.http`` block
    on any step also promotes the scenario to at least ``medium``
    because it performs an outbound HTTP request from the bridge
    host (SSRF-adjacent) which the caller must consent to.
    """
    max_score = 0
    for step in doc.get("steps") or []:
        tool = str(step.get("tool") or "").strip()
        if tool:
            risk = classify_tool_risk(tool)
            score = RISK_ORDER.get(risk, 1)
            if score > max_score:
                max_score = score
        wait_for = step.get("wait_for") or {}
        if isinstance(wait_for, dict) and wait_for.get("http"):
            # http probe from the bridge host = medium at least.
            if max_score < RISK_ORDER["medium"]:
                max_score = RISK_ORDER["medium"]
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


# ---------------------------------------------------------------
# v4.54.1: retry + wait_for helpers
# ---------------------------------------------------------------
def _normalise_retry(spec: dict[str, Any]) -> dict[str, Any]:
    """Read a step's optional ``retry:`` block into normalised form.

    Defaults: 1 attempt (no retry), 0.5 s initial delay,
    2.0x backoff. All numeric fields are clamped to sane
    bounds so a runaway scenario can't spin forever.
    """
    raw = spec.get("retry")
    if not isinstance(raw, dict):
        return {"attempts": 1, "delay_seconds": 0.0, "backoff": 1.0}
    attempts = max(1, min(int(raw.get("attempts") or 1), 10))
    delay = max(0.0, min(float(raw.get("delay_seconds") or 0.5), 60.0))
    backoff = max(1.0, min(float(raw.get("backoff") or 2.0), 5.0))
    return {"attempts": attempts, "delay_seconds": delay, "backoff": backoff}


def _normalise_wait_for(spec: dict[str, Any]) -> dict[str, Any] | None:
    """Read a step's optional ``wait_for:`` block.

    Two shapes supported:

    * ``{"file": "~/Downloads/note.m4a", "timeout_seconds": 30,
        "poll_seconds": 1}`` — wait until file exists.
    * ``{"http": {"url": "https://x/status", "expect_status": 200,
                   "expect_json_field": "done", "expect_json_value": true},
        "timeout_seconds": 30, "poll_seconds": 2}`` — poll URL
      until status matches AND optional json field equals value.

    Returns ``None`` if no ``wait_for`` block, else a normalised
    dict. Never raises on schema issues — invalid blocks silently
    normalise to defaults and the wait immediately succeeds so a
    typo doesn't block the whole scenario.
    """
    raw = spec.get("wait_for")
    if not isinstance(raw, dict):
        return None
    # Explicit 0 is a bug we should clamp, not a signal to use
    # the default -- hence `if val is None else val` rather than `or`.
    _t = raw.get("timeout_seconds")
    _p = raw.get("poll_seconds")
    timeout = max(1.0, min(float(30 if _t is None else _t), 3600.0))
    poll = max(0.1, min(float(1.0 if _p is None else _p), 30.0))
    out: dict[str, Any] = {"timeout_seconds": timeout, "poll_seconds": poll}
    if "file" in raw:
        out["file"] = str(raw["file"])
    http = raw.get("http")
    if isinstance(http, dict) and http.get("url"):
        out["http"] = {
            "url": str(http["url"]),
            "expect_status": int(http.get("expect_status") or 200),
            "expect_json_field": str(http.get("expect_json_field") or ""),
            "expect_json_value": http.get("expect_json_value"),
            "method": str(http.get("method") or "GET").upper(),
        }
    if "file" not in out and "http" not in out:
        return None
    return out


def _wait_for_file(path_str: str, timeout: float, poll: float) -> dict[str, Any]:
    p = Path(path_str).expanduser()
    started = time.time()
    while True:
        if p.exists():
            try:
                size = p.stat().st_size
            except OSError:
                size = -1
            return {
                "ok": True, "kind": "file", "path": str(p),
                "size_bytes": size,
                "waited_seconds": round(time.time() - started, 3),
            }
        if time.time() - started >= timeout:
            return {
                "ok": False, "kind": "file", "path": str(p),
                "error": f"file did not appear within {timeout}s",
                "waited_seconds": round(time.time() - started, 3),
            }
        time.sleep(poll)


_WAIT_FOR_HTTP_ALLOWED_SCHEMES = ("http://", "https://")


def _wait_for_http(cfg: dict[str, Any], timeout: float, poll: float) -> dict[str, Any]:
    url = cfg["url"]
    if not any(url.startswith(p) for p in _WAIT_FOR_HTTP_ALLOWED_SCHEMES):
        return {"ok": False, "kind": "http", "url": url,
                "error": "only http/https URLs are allowed for wait_for.http"}
    started = time.time()
    last_status: int | None = None
    last_error: str | None = None
    while True:
        try:
            req = urllib.request.Request(url, method=cfg["method"])
            with urllib.request.urlopen(req, timeout=min(10.0, poll * 5)) as resp:  # nosec B310 -- scenario wait_for.http URL is user-supplied and gated behind medium+ risk classification; timeout is bounded to keep the poller responsive.
                status = int(resp.status or 0)
                body = resp.read(65536)
                last_status = status
                # Status match check.
                status_ok = status == cfg["expect_status"]
                # Optional JSON field match.
                json_ok = True
                json_field = cfg.get("expect_json_field", "")
                if status_ok and json_field:
                    try:
                        parsed = json.loads(body.decode("utf-8", "replace"))
                        actual = _resolve_path(parsed, json_field)
                        expected = cfg.get("expect_json_value")
                        json_ok = actual == expected
                    except Exception:
                        json_ok = False
                if status_ok and json_ok:
                    return {
                        "ok": True, "kind": "http", "url": url,
                        "status": status,
                        "waited_seconds": round(time.time() - started, 3),
                    }
        except urllib.error.HTTPError as e:
            last_status = e.code
            last_error = f"HTTP {e.code}"
        except Exception as e:
            last_error = f"{type(e).__name__}: {e}"
        if time.time() - started >= timeout:
            return {
                "ok": False, "kind": "http", "url": url,
                "status": last_status, "error": last_error or "condition not met",
                "waited_seconds": round(time.time() - started, 3),
            }
        time.sleep(poll)


def _do_wait_for(wait_cfg: dict[str, Any]) -> dict[str, Any]:
    timeout = wait_cfg["timeout_seconds"]
    poll = wait_cfg["poll_seconds"]
    if "file" in wait_cfg:
        return _wait_for_file(wait_cfg["file"], timeout, poll)
    if "http" in wait_cfg:
        return _wait_for_http(wait_cfg["http"], timeout, poll)
    return {"ok": True, "kind": "noop"}


class ScenariosRuntime:
    """Loads scenarios from mission-storage and runs them via a tool dispatcher.

    v4.55.0: storage is now a :class:`ScenarioMissionStore` that
    reads/writes scenarios as missions with ``template='scenario'``.
    The public API on this class is unchanged from v4.54.x — only
    the underlying persistence moved.
    """

    def __init__(
        self,
        storage: ScenarioMissionStore,
        dispatch: Callable[[str, dict[str, Any]], dict[str, Any]],
    ) -> None:
        self._storage = storage
        self._dispatch = dispatch

    @property
    def storage(self) -> ScenarioMissionStore:
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

            # v4.54.1: retry + wait_for handling.
            retry_cfg = _normalise_retry(spec)
            wait_cfg = _normalise_wait_for(spec)
            attempts_seen = 0
            ok = False
            result: dict[str, Any] = {}
            error: str | None = None
            delay = retry_cfg["delay_seconds"]
            wait_info: dict[str, Any] | None = None
            for attempt in range(retry_cfg["attempts"]):
                attempts_seen = attempt + 1
                try:
                    raw = self._dispatch(tool, args)
                    result = raw if isinstance(raw, dict) else {"value": raw}
                    ok = bool(result.get("ok", True)) and not result.get("isError")
                    error = None if ok else str(result.get("error") or "step failed")
                except Exception as exc:
                    ok = False
                    result = {"ok": False, "error": str(exc)}
                    error = str(exc)
                if ok:
                    # Tool call succeeded; now wait_for post-condition
                    # (if any). A failed wait_for demotes the whole
                    # attempt so the retry loop can try again.
                    if wait_cfg is not None:
                        wait_info = _do_wait_for(wait_cfg)
                        if not wait_info.get("ok"):
                            ok = False
                            error = f"wait_for failed: {wait_info.get('error') or 'condition not met'}"
                            # Attach wait_info to the result so operators
                            # can see what timed out.
                            result = {**result, "wait_for": wait_info}
                    if ok:
                        # Also attach a successful wait_info if any.
                        if wait_info is not None:
                            result = {**result, "wait_for": wait_info}
                        break
                # Failed attempt -- if retries remain, sleep with backoff.
                if attempt + 1 < retry_cfg["attempts"]:
                    time.sleep(delay)
                    delay *= retry_cfg["backoff"]

            if attempts_seen > 1:
                # Surface how many attempts we needed so debugging isn't
                # a mystery when a flaky tool eventually succeeds.
                result = {**result, "attempts_used": attempts_seen}

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
        self._storage.append_run(got["name"], run.to_dict())
        return run


def build_scenarios_runtime(
    dispatch: Callable[[str, dict[str, Any]], dict[str, Any]],
    *,
    storage: ScenarioMissionStore | None = None,
) -> ScenariosRuntime:
    return ScenariosRuntime(storage or ScenarioMissionStore(), dispatch)


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
