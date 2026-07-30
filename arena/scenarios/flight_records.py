"""Scenario flight records: durable real-machine proof notes.

A scenario run can be technically successful while the observer-visible
outcome is not.  Flight records capture that distinction in a compact,
artifact-friendly JSON + Markdown pair under the scenario mission directory.
"""
from __future__ import annotations

import datetime as dt
import json
import re
import uuid
from pathlib import Path
from typing import Any

from arena.scenarios.mission_bridge import ScenarioMissionStore


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def _safe_slug(value: str, *, fallback: str = "record") -> str:
    s = re.sub(r"[^a-zA-Z0-9._-]+", "-", str(value or "").strip()).strip("-").lower()
    return s[:80] or fallback


def _clean_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _jsonable(value: Any) -> Any:
    try:
        json.dumps(value)
        return value
    except Exception:
        return str(value)


def _records_dir(scenario_path: str | Path) -> Path:
    p = Path(scenario_path) / "artifacts" / "flight-records"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _scenario_path(storage: ScenarioMissionStore, name: str) -> Path:
    got = storage.get(name)
    return Path(got["path"])


def render_markdown(record: dict[str, Any]) -> str:
    lines: list[str] = []
    title = record.get("title") or record.get("name") or "Scenario flight record"
    lines.append(f"# {title}")
    lines.append("")
    lines.append(f"- Scenario: `{record.get('name')}`")
    lines.append(f"- Record ID: `{record.get('record_id')}`")
    lines.append(f"- Created: `{record.get('created_at')}`")
    lines.append(f"- Status: `{record.get('status', 'unknown')}`")
    if record.get("outcome"):
        lines.append(f"- Outcome: {record['outcome']}")
    if record.get("risk"):
        lines.append(f"- Risk: `{record['risk']}`")
    lines.append("")

    def section(name: str, value: Any) -> None:
        if value in (None, "", [], {}):
            return
        lines.append(f"## {name}")
        lines.append("")
        if isinstance(value, str):
            lines.append(value)
        elif isinstance(value, list):
            for item in value:
                if isinstance(item, dict):
                    label = item.get("title") or item.get("name") or item.get("id") or item.get("tool") or "item"
                    lines.append(f"- **{label}**: `{json.dumps(_jsonable(item), ensure_ascii=False)}`")
                else:
                    lines.append(f"- {item}")
        else:
            lines.append("```json")
            lines.append(json.dumps(_jsonable(value), ensure_ascii=False, indent=2))
            lines.append("```")
        lines.append("")

    section("Boundary", record.get("boundary"))
    section("Summary", record.get("summary"))
    section("Observations", record.get("observations"))
    section("Artifacts", record.get("artifacts"))
    section("Commands / tool calls", record.get("commands"))
    section("What worked", record.get("worked"))
    section("What did not work", record.get("not_worked"))
    section("Next steps", record.get("next_steps"))
    section("Raw data", record.get("data"))
    return "\n".join(lines).rstrip() + "\n"


def create_record(
    name: str,
    *,
    title: str = "",
    status: str = "observed",
    outcome: str = "",
    boundary: str | list[Any] | dict[str, Any] | None = None,
    summary: str | list[Any] | dict[str, Any] | None = None,
    observations: Any = None,
    artifacts: Any = None,
    commands: Any = None,
    worked: Any = None,
    not_worked: Any = None,
    next_steps: Any = None,
    data: Any = None,
    risk: str = "",
    tags: Any = None,
    storage: ScenarioMissionStore | None = None,
) -> dict[str, Any]:
    storage = storage or ScenarioMissionStore()
    scenario_dir = _scenario_path(storage, name)
    rid = f"{dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:8]}"
    record = {
        "record_id": rid,
        "name": name,
        "title": title or f"{name} flight record",
        "created_at": _now(),
        "status": status,
        "outcome": outcome,
        "risk": risk,
        "tags": _clean_list(tags),
        "boundary": _jsonable(boundary),
        "summary": _jsonable(summary),
        "observations": _jsonable(_clean_list(observations)),
        "artifacts": _jsonable(_clean_list(artifacts)),
        "commands": _jsonable(_clean_list(commands)),
        "worked": _jsonable(_clean_list(worked)),
        "not_worked": _jsonable(_clean_list(not_worked)),
        "next_steps": _jsonable(_clean_list(next_steps)),
        "data": _jsonable(data or {}),
    }
    out_dir = _records_dir(scenario_dir)
    stem = _safe_slug(rid)
    json_path = out_dir / f"{stem}.json"
    md_path = out_dir / f"{stem}.md"
    json_path.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    md_path.write_text(render_markdown(record), encoding="utf-8")
    return {
        "ok": True,
        "name": name,
        "record_id": rid,
        "json_path": str(json_path),
        "markdown_path": str(md_path),
        "record": record,
    }


def list_records(name: str, *, storage: ScenarioMissionStore | None = None) -> dict[str, Any]:
    storage = storage or ScenarioMissionStore()
    scenario_dir = _scenario_path(storage, name)
    out_dir = _records_dir(scenario_dir)
    records = []
    for p in sorted(out_dir.glob("*.json"), key=lambda x: x.name, reverse=True):
        try:
            obj = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        md = p.with_suffix(".md")
        records.append({
            "record_id": obj.get("record_id"),
            "created_at": obj.get("created_at"),
            "title": obj.get("title"),
            "status": obj.get("status"),
            "outcome": obj.get("outcome"),
            "json_path": str(p),
            "markdown_path": str(md) if md.exists() else None,
        })
    return {"ok": True, "name": name, "count": len(records), "records": records}


def get_report(name: str, *, record_id: str = "", latest: bool = True, storage: ScenarioMissionStore | None = None) -> dict[str, Any]:
    storage = storage or ScenarioMissionStore()
    scenario_dir = _scenario_path(storage, name)
    out_dir = _records_dir(scenario_dir)
    target_json: Path | None = None
    if record_id:
        for p in out_dir.glob("*.json"):
            try:
                obj = json.loads(p.read_text(encoding="utf-8"))
            except Exception:
                continue
            if str(obj.get("record_id")) == record_id:
                target_json = p
                break
    elif latest:
        files = sorted(out_dir.glob("*.json"), key=lambda x: x.name, reverse=True)
        target_json = files[0] if files else None
    if target_json is None:
        return {"ok": False, "error": "flight_record_not_found", "name": name, "record_id": record_id or None}
    record = json.loads(target_json.read_text(encoding="utf-8"))
    md_path = target_json.with_suffix(".md")
    markdown = md_path.read_text(encoding="utf-8") if md_path.exists() else render_markdown(record)
    return {
        "ok": True,
        "name": name,
        "record_id": record.get("record_id"),
        "record": record,
        "markdown": markdown,
        "json_path": str(target_json),
        "markdown_path": str(md_path),
    }


__all__ = ["create_record", "get_report", "list_records", "render_markdown"]
