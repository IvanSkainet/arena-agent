"""Scenario storage sitting on top of the mission filesystem.

v4.55.0: dropped ``~/.arena/scenarios/`` in favour of the
existing mission directory (``<ARENA_AGENT_HOME>/missions/``).
Each scenario becomes a mission with ``template="scenario"`` and
a ``template_data.steps`` array containing the tool-call spec.
Every mission surface (``mission.catalog``, ``mission.status``,
``mission.history``, ``mission.report``, ``mission.schedule_*``)
now works on scenarios without any extra plumbing — that was the
whole point of the merge.

Ivan reviewed the design and picked "step_field" (any mission
template can carry tool-call steps) + "drop_old" (no data
migration, breaking change).
"""
from __future__ import annotations

import datetime as dt
import json
import os
import re
import uuid
from pathlib import Path
from typing import Any

from arena.scenarios.storage import (
    InvalidScenario,
    ScenarioNotFound,
    parse_scenario_source,
    render_scenario_source,
    validate_name,
)


SCENARIO_TEMPLATE_ID = "scenario"


def resolve_missions_dir() -> Path:
    """Return the missions dir the mission_manager CLI uses.

    Mirrors ``arena/missions_cli/common.py::MISSIONS`` — env
    ``ARENA_AGENT_HOME`` overrides, otherwise ``~/arena-bridge``.
    """
    root = Path(os.environ.get("ARENA_AGENT_HOME", str(Path.home() / "arena-bridge"))).expanduser()
    return root / "missions"


def _slug(name: str) -> str:
    n = str(name or "").strip().lower()
    n = re.sub(r"[^a-zA-Z0-9._-]+", "-", n).strip("-").lower() or "scenario"
    return n


def _now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def _mission_id(scenario_name: str) -> str:
    """Deterministic mission id from a scenario name.

    Format ``scenario-<slug>`` so mission.catalog output reads
    naturally and human recognition works. Idempotent per name.
    """
    return f"scenario-{_slug(scenario_name)}"


def _find_by_name(missions_dir: Path, scenario_name: str) -> Path | None:
    """Find a scenario-typed mission by its scenario name.

    Returns the mission directory or None. Preserves back-compat
    with ANY mission whose template_data.name matches, not just
    the deterministic slug form.
    """
    mid = _mission_id(scenario_name)
    exact = missions_dir / mid
    if exact.is_dir() and (exact / "mission.json").exists():
        return exact
    if missions_dir.exists():
        for p in missions_dir.iterdir():
            if not p.is_dir() or not (p / "mission.json").exists():
                continue
            try:
                obj = json.loads((p / "mission.json").read_text(encoding="utf-8"))
            except Exception:
                continue
            if obj.get("template") != SCENARIO_TEMPLATE_ID:
                continue
            td = obj.get("template_data") or {}
            if str(td.get("name") or "") == scenario_name:
                return p
    return None


class ScenarioMissionStore:
    """CRUD for scenario missions in ``<agent_home>/missions/``."""

    def __init__(self, missions_dir: Path | None = None) -> None:
        self._dir = missions_dir or resolve_missions_dir()

    @property
    def missions_dir(self) -> Path:
        return self._dir

    def ensure_dir(self) -> None:
        self._dir.mkdir(parents=True, exist_ok=True)

    def list(self) -> list[dict[str, Any]]:
        self.ensure_dir()
        out: list[dict[str, Any]] = []
        for p in sorted(self._dir.iterdir(), key=lambda x: x.name):
            if not p.is_dir():
                continue
            mj = p / "mission.json"
            if not mj.exists():
                continue
            try:
                obj = json.loads(mj.read_text(encoding="utf-8"))
            except Exception:
                continue
            if obj.get("template") != SCENARIO_TEMPLATE_ID:
                continue
            td = obj.get("template_data") or {}
            steps = td.get("steps") or []
            out.append({
                "name": str(td.get("name") or p.name.removeprefix("scenario-")),
                "mission_id": obj.get("id") or p.name,
                "title": str(obj.get("title", "")),
                "description": str(td.get("description", "")),
                "step_count": len(steps),
                "tools": sorted({
                    str(s.get("tool") or "") for s in steps if s.get("tool")
                }),
                "state": obj.get("state", "planned"),
                "created_at": obj.get("created_at", ""),
                "path": str(p),
            })
        return out

    def get(self, scenario_name: str) -> dict[str, Any]:
        n = validate_name(scenario_name)
        d = _find_by_name(self._dir, n)
        if d is None:
            raise ScenarioNotFound(scenario_name)
        mj = d / "mission.json"
        obj = json.loads(mj.read_text(encoding="utf-8"))
        td = obj.get("template_data") or {}
        doc = {
            "name": n,
            "title": obj.get("title", ""),
            "description": td.get("description", ""),
            "steps": td.get("steps") or [],
        }
        return {
            "name": n,
            "mission_id": obj.get("id"),
            "doc": doc,
            "source": render_scenario_source(doc),
            "path": str(d),
        }

    def save(self, scenario_name: str, source_text: str,
             *, overwrite: bool = True) -> dict[str, Any]:
        n = validate_name(scenario_name)
        parsed = parse_scenario_source(source_text)
        parsed["name"] = n
        steps = parsed.get("steps") or []

        mid = _mission_id(n)
        d = self._dir / mid
        exists = d.is_dir() and (d / "mission.json").exists()
        if exists and not overwrite:
            raise InvalidScenario(f"scenario {n!r} already exists (overwrite=False)")

        self.ensure_dir()
        d.mkdir(parents=True, exist_ok=True)
        (d / "logs").mkdir(exist_ok=True)
        (d / "artifacts").mkdir(exist_ok=True)

        # Preserve runs[] and state on overwrite so we don't wipe
        # execution history when a user re-saves a scenario.
        existing_runs: list[dict[str, Any]] = []
        existing_state = "planned"
        if exists:
            try:
                old = json.loads((d / "mission.json").read_text(encoding="utf-8"))
                existing_runs = old.get("runs") or []
                existing_state = old.get("state", "planned")
            except Exception:
                pass

        obj = {
            "id": mid,
            "template": SCENARIO_TEMPLATE_ID,
            "title": parsed.get("title", n),
            "created_at": _now_iso() if not exists else (
                json.loads((d / "mission.json").read_text(encoding="utf-8")).get("created_at", _now_iso())
                if exists else _now_iso()
            ),
            "updated_at": _now_iso(),
            "state": existing_state,
            "template_data": {
                "name": n,
                "description": parsed.get("description", ""),
                "steps": steps,
            },
            "runs": existing_runs,
        }
        (d / "mission.json").write_text(
            json.dumps(obj, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        return {"name": n, "mission_id": mid, "path": str(d), "step_count": len(steps)}

    def delete(self, scenario_name: str) -> dict[str, Any]:
        n = validate_name(scenario_name)
        d = _find_by_name(self._dir, n)
        if d is None:
            raise ScenarioNotFound(scenario_name)
        # Physical delete of the whole mission directory. Consistent
        # with `rm ~/arena-bridge/missions/scenario-foo`.
        import shutil
        shutil.rmtree(d)
        return {"name": n, "deleted": True}

    def append_run(self, scenario_name: str, run: dict[str, Any]) -> None:
        n = validate_name(scenario_name)
        d = _find_by_name(self._dir, n)
        if d is None:
            return
        mj = d / "mission.json"
        try:
            obj = json.loads(mj.read_text(encoding="utf-8"))
        except Exception:
            return
        obj.setdefault("runs", []).append({**run, "recorded_at": _now_iso()})
        # Keep only last 20 runs -- mission history has no
        # explicit cap, but scenarios are more chatty (retries,
        # wait_for cycles) so we bound growth here.
        obj["runs"] = obj["runs"][-20:]
        obj["state"] = "done" if run.get("ok") else "failed"
        obj["finished_at"] = _now_iso()
        mj.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    def load_history(self, scenario_name: str) -> list[dict[str, Any]]:
        n = validate_name(scenario_name)
        d = _find_by_name(self._dir, n)
        if d is None:
            return []
        try:
            obj = json.loads((d / "mission.json").read_text(encoding="utf-8"))
        except Exception:
            return []
        return list(obj.get("runs") or [])


__all__ = [
    "ScenarioMissionStore",
    "SCENARIO_TEMPLATE_ID",
    "resolve_missions_dir",
]
