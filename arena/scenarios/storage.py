"""Filesystem storage for scenario documents.

Scenarios live at ``$ARENA_SCENARIOS_DIR`` (defaults to
``~/.arena/scenarios/<name>.json``). Each file is a single
JSON document with the shape::

    {
      "name": "hello-world",
      "title": "Optional human title",
      "description": "Optional longer description",
      "steps": [
        {"id": "status", "tool": "sys.status", "arguments": {}},
        {"id": "report", "return": "Bridge {{ steps.status.result.version }}"}
      ]
    }

YAML source is also accepted on save if PyYAML happens to be
installed (opt-in via ``ARENA_SCENARIOS_ALLOW_YAML=1``). The
canonical stored form is always JSON so the bridge never has
a hard PyYAML dependency and reads work in any environment.

History is stored in a sibling ``<name>.history.json`` file
with the last 20 runs (oldest first).
"""
from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path
from typing import Any


_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")

HISTORY_KEEP = 20


class InvalidScenario(ValueError):
    """Raised when scenario document fails schema validation."""


class ScenarioNotFound(FileNotFoundError):
    """Raised when a scenario name cannot be resolved on disk."""


def resolve_scenarios_dir() -> Path:
    """Directory where scenario YAML documents live.

    Honours ``ARENA_SCENARIOS_DIR`` env for tests / opt-in
    relocations. Falls back to ``~/.arena/scenarios`` per Ivan's
    v4.54.0 answer to the storage question.
    """
    env = os.environ.get("ARENA_SCENARIOS_DIR", "").strip()
    if env:
        return Path(env).expanduser()
    return Path.home() / ".arena" / "scenarios"


def _validate_name(name: str) -> str:
    n = str(name or "").strip().lower()
    if not _NAME_RE.match(n):
        raise InvalidScenario(
            f"invalid scenario name {n!r}; must match [a-z0-9][a-z0-9._-]{{0,63}}"
        )
    return n


def _try_yaml_parse(text: str) -> dict[str, Any] | None:
    """Try YAML parse if PyYAML is available AND opt-in env is set.

    Returns None if YAML support is unavailable/disabled. Callers
    fall through to JSON in that case.
    """
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
    """Parse a scenario source into a validated dict.

    Format detection: if the text starts with ``{`` (after
    stripping whitespace/BOM) or has ``ARENA_SCENARIOS_ALLOW_YAML``
    unset, it's parsed as JSON. Otherwise YAML is attempted first
    with a JSON fallback. Never raises anything other than
    :class:`InvalidScenario`.
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
        # Try YAML first if opt-in; else JSON as a last resort.
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
    # name is optional in the file (falls back to filename stem)
    if "name" in doc:
        doc["name"] = _validate_name(doc["name"])
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
        # continue_on_error (bool) is optional; anything else stays untouched
    return doc


def render_scenario_source(doc: dict[str, Any]) -> str:
    """Canonical serialisation of a scenario doc.

    Always JSON (2-space indent, unicode preserved) so files can
    be diffed reliably. YAML on-disk was considered but rejected:
    it hides a PyYAML dependency at read time which broke
    `scenario.save` in Ivan's v4.54.0 first-boot smoke.
    """
    return json.dumps(doc, indent=2, ensure_ascii=False, sort_keys=False)


class ScenariosStorage:
    """Read/write scenario YAML documents + per-scenario history."""

    def __init__(self, base_dir: Path | None = None) -> None:
        self._base = base_dir or resolve_scenarios_dir()

    @property
    def base_dir(self) -> Path:
        return self._base

    def ensure_dir(self) -> None:
        self._base.mkdir(parents=True, exist_ok=True)

    def _yaml_path(self, name: str) -> Path:
        return self._base / f"{_validate_name(name)}.json"

    def _history_path(self, name: str) -> Path:
        return self._base / f"{_validate_name(name)}.history.json"

    def list(self) -> list[dict[str, Any]]:
        self.ensure_dir()
        out: list[dict[str, Any]] = []
        for entry in sorted(self._base.glob("*.json")):
            # Skip history files: <name>.history.json.
            if entry.name.endswith(".history.json"):
                continue
            try:
                text = entry.read_text(encoding="utf-8")
                doc = parse_scenario_source(text)
            except InvalidScenario:
                continue
            name = str(doc.get("name") or entry.stem)
            out.append({
                "name": name,
                "title": str(doc.get("title", "")),
                "description": str(doc.get("description", "")),
                "step_count": len(doc.get("steps") or []),
                "tools": sorted({
                    str(s.get("tool") or "") for s in (doc.get("steps") or []) if s.get("tool")
                }),
                "path": str(entry),
                "mtime": entry.stat().st_mtime,
            })
        return out

    def get(self, name: str) -> dict[str, Any]:
        p = self._yaml_path(name)
        if not p.exists():
            raise ScenarioNotFound(name)
        text = p.read_text(encoding="utf-8")
        doc = parse_scenario_source(text)
        doc.setdefault("name", _validate_name(name))
        return {"name": doc["name"], "doc": doc, "source": text, "path": str(p)}

    def save(self, name: str, source_text: str, *, overwrite: bool = True) -> dict[str, Any]:
        n = _validate_name(name)
        doc = parse_scenario_source(source_text)
        doc["name"] = n
        # Round-trip so we always store a clean dump.
        canonical = render_scenario_source(doc)
        p = self._yaml_path(n)
        self.ensure_dir()
        if p.exists() and not overwrite:
            raise InvalidScenario(f"scenario {n!r} already exists (overwrite=False)")
        p.write_text(canonical, encoding="utf-8")
        return {"name": n, "path": str(p), "step_count": len(doc.get("steps") or [])}

    def delete(self, name: str) -> dict[str, Any]:
        n = _validate_name(name)
        p = self._yaml_path(n)
        h = self._history_path(n)
        deleted = False
        if p.exists():
            p.unlink()
            deleted = True
        if h.exists():
            h.unlink()
        if not deleted:
            raise ScenarioNotFound(n)
        return {"name": n, "deleted": True}

    # ---- history ------------------------------------------------
    def load_history(self, name: str) -> list[dict[str, Any]]:
        p = self._history_path(name)
        if not p.exists():
            return []
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            return []
        entries = data if isinstance(data, list) else data.get("runs", [])
        return list(entries)[-HISTORY_KEEP:]

    def append_history(self, name: str, run: dict[str, Any]) -> None:
        n = _validate_name(name)
        entries = self.load_history(n)
        entries.append({**run, "recorded_at": time.strftime("%Y-%m-%dT%H:%M:%S")})
        entries = entries[-HISTORY_KEEP:]
        self.ensure_dir()
        self._history_path(n).write_text(
            json.dumps(entries, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )


__all__ = [
    "ScenariosStorage",
    "ScenarioNotFound",
    "InvalidScenario",
    "resolve_scenarios_dir",
    "parse_scenario_source",
    "render_scenario_source",
    "HISTORY_KEEP",
]
