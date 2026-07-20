"""Scenario schema validation.

v4.55.0: scenarios are stored as missions with template='scenario'.
Their canonical location is now ``<ARENA_AGENT_HOME>/missions/
<mission_id>/mission.json`` (same directory the mission manager
already uses). This module only owns the SCHEMA — the actual
CRUD lives in :mod:`arena.scenarios.mission_bridge`.

The parser here accepts JSON (canonical) or YAML (opt-in via
``ARENA_SCENARIOS_ALLOW_YAML=1``) source text and returns a
validated dict with a ``steps`` array. Same validation rules
as v4.54.0/1 — no schema change for authors.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any


_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")


class InvalidScenario(ValueError):
    """Raised when scenario source fails schema validation."""


class ScenarioNotFound(FileNotFoundError):
    """Raised when a scenario name/mission_id cannot be resolved."""


def validate_name(name: str) -> str:
    n = str(name or "").strip().lower()
    if not _NAME_RE.match(n):
        raise InvalidScenario(
            f"invalid scenario name {n!r}; must match [a-z0-9][a-z0-9._-]{{0,63}}"
        )
    return n


def _try_yaml_parse(text: str) -> dict[str, Any] | None:
    if os.environ.get("ARENA_SCENARIOS_ALLOW_YAML", "").strip() not in {"1", "true", "yes"}:
        return None
    try:
        import yaml  # type: ignore
    except Exception:
        return None
    try:
        doc = yaml.safe_load(text or "") or {}
    except Exception as exc:
        raise InvalidScenario(f"yaml parse error: {exc}") from exc
    if not isinstance(doc, dict):
        raise InvalidScenario("scenario root must be a mapping")
    return doc


def parse_scenario_source(text: str) -> dict[str, Any]:
    """Parse a scenario source (JSON or optional YAML) and validate schema.

    Raises :class:`InvalidScenario` on any structural problem.
    """
    src = (text or "").lstrip("\ufeff \n\r\t")
    doc: dict[str, Any] | None = None
    if src.startswith(("{", "[")):
        try:
            doc = json.loads(src)
        except Exception as exc:
            raise InvalidScenario(f"json parse error: {exc}") from exc
        if not isinstance(doc, dict):
            raise InvalidScenario("scenario root must be a mapping")
    else:
        doc = _try_yaml_parse(src)
        if doc is None:
            try:
                doc = json.loads(src)
            except Exception as exc:
                raise InvalidScenario(
                    "expected JSON scenario document (set "
                    "ARENA_SCENARIOS_ALLOW_YAML=1 to also accept YAML)"
                ) from exc
            if not isinstance(doc, dict):
                raise InvalidScenario("scenario root must be a mapping")

    if "name" in doc:
        doc["name"] = validate_name(doc["name"])
    steps = doc.get("steps")
    if not isinstance(steps, list) or not steps:
        raise InvalidScenario("scenario must have a non-empty steps list")
    seen_ids: set[str] = set()
    for idx, step in enumerate(steps, start=1):
        if not isinstance(step, dict):
            raise InvalidScenario(f"step {idx} must be a mapping")
        sid = str(step.get("id") or f"step{idx}")
        if sid in seen_ids:
            raise InvalidScenario(f"duplicate step id {sid!r}")
        seen_ids.add(sid)
        step["id"] = sid
        has_tool = bool(str(step.get("tool") or "").strip())
        has_return = "return" in step
        if not has_tool and not has_return:
            raise InvalidScenario(f"step {sid!r} must have either `tool` or `return`")
        if has_tool and "arguments" in step and not isinstance(step["arguments"], dict):
            raise InvalidScenario(f"step {sid!r} arguments must be a mapping")
    return doc


def render_scenario_source(doc: dict[str, Any]) -> str:
    """Canonical JSON dump — used by tests + mission migration."""
    return json.dumps(doc, indent=2, ensure_ascii=False, sort_keys=False)


__all__ = [
    "InvalidScenario",
    "ScenarioNotFound",
    "parse_scenario_source",
    "render_scenario_source",
    "validate_name",
]
