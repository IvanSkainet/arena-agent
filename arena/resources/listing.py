"""Resource listing/show helpers."""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from arena.resources.mission_catalog import summarize_mission_dir
from arena.resources.mission_identifier import resolve_mission_name


def list_missions(missions_dir: Path) -> list[dict[str, Any]]:
    missions: list[dict[str, Any]] = []
    if missions_dir.exists():
        for path in sorted(missions_dir.iterdir()):
            if path.is_file() and path.suffix in (".json", ".yaml", ".yml", ".md", ".txt"):
                missions.append({"name": path.stem, "ext": path.suffix, "size": path.stat().st_size, "modified": datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat()})
            elif path.is_dir():
                if (path / "mission.json").exists():
                    missions.append(summarize_mission_dir(path))
                else:
                    missions.append({"name": path.name, "ext": "[dir]", "size": len(list(path.iterdir())), "modified": datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat()})
    return missions


def show_mission(missions_dir: Path, name: str) -> dict[str, Any]:
    """Read a mission file or directory by name.

    v4.171.0 (#130): this helper predates `mission_dir` and does its own
    lookup, so it did not get the scenario-name resolution the other
    five mission readers received -- `/v1/mission/show` 404'd on the
    short name from `scenario.list` while `/v1/mission/status` answered
    200 for the very same identifier. Resolve here too; the traversal
    guard below still runs on the caller's original input.
    """
    if ".." in name or "/" in name or "\\" in name or name.startswith("."):
        return {"ok": False, "error": "invalid mission name"}
    name = resolve_mission_name(missions_dir, name)
    for ext in ("", ".json", ".yaml", ".yml", ".md", ".txt"):
        path = missions_dir / f"{name}{ext}"
        if path.exists() and path.is_file():
            content = path.read_text(encoding="utf-8", errors="replace")
            return {"ok": True, "name": name, "file": str(path), "ext": path.suffix or ext, "content": content, "size": path.stat().st_size}
    directory = missions_dir / name
    if directory.exists() and directory.is_dir():
        files = []
        for item in sorted(directory.iterdir()):
            files.append({"name": item.name, "size": item.stat().st_size if item.is_file() else 0, "is_dir": item.is_dir()})
        payload: dict[str, Any] = {"ok": True, "name": name, "is_dir": True, "files": files}
        if (directory / "mission.json").exists():
            payload["mission"] = summarize_mission_dir(directory)
        return payload
    return {"ok": False, "error": f"mission '{name}' not found"}


def list_reports(reports_dir: Path) -> list[dict[str, Any]]:
    reports: list[dict[str, Any]] = []
    if reports_dir.exists():
        for path in sorted(reports_dir.iterdir()):
            if path.is_file():
                reports.append({"name": path.name, "size": path.stat().st_size, "modified": datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat()})
    shots_dir = reports_dir / "shots"
    if shots_dir.exists():
        for path in sorted(shots_dir.iterdir()):
            if path.is_file():
                reports.append({"name": f"shots/{path.name}", "size": path.stat().st_size, "modified": datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat()})
    return reports


def list_hooks(hooks_dir: Path) -> dict[str, Any]:
    hooks: list[dict[str, Any]] = []
    if not hooks_dir.exists():
        return {"ok": True, "count": 0, "hooks": []}
    for path in sorted(hooks_dir.iterdir()):
        if path.is_file() and path.suffix in (".json", ".yaml", ".yml", ".toml"):
            info: dict[str, Any] = {"name": path.stem, "file": path.name, "ext": path.suffix, "size": path.stat().st_size}
            if path.suffix == ".json":
                try:
                    data = json.loads(path.read_text(encoding="utf-8"))
                    info["event"] = data.get("event", "")
                    info["description"] = data.get("description", "")
                except Exception:
                    pass
            hooks.append(info)
    return {"ok": True, "count": len(hooks), "hooks": hooks}


def list_agents(agents_dir: Path) -> dict[str, Any]:
    agents: list[dict[str, Any]] = []
    if not agents_dir.exists():
        return {"ok": True, "count": 0, "agents": []}
    for path in sorted(agents_dir.iterdir()):
        if path.is_file() and path.suffix in (".json", ".yaml", ".yml", ".toml", ".md"):
            info: dict[str, Any] = {"name": path.stem, "file": path.name, "ext": path.suffix, "size": path.stat().st_size}
            if path.suffix == ".json":
                try:
                    data = json.loads(path.read_text(encoding="utf-8"))
                    info["description"] = data.get("description", "")
                    info["model"] = data.get("model", "")
                except Exception:
                    pass
            agents.append(info)
        elif path.is_dir():
            agents.append({"name": path.name, "file": f"{path.name}/", "ext": "[dir]", "size": len(list(path.iterdir()))})
    return {"ok": True, "count": len(agents), "agents": agents}


SUBAGENT_FILE_SUFFIXES = (".json", ".yaml", ".yml", ".toml", ".md")


def _read_json_dict(path: Path) -> dict[str, Any] | None:
    """Return the JSON object at *path*, or None when unreadable/not an object."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _dir_entry_count(directory: Path) -> int:
    try:
        return sum(1 for _ in directory.iterdir())
    except OSError:
        return 0


def _mtime_iso(path: Path, stat_result: os.stat_result | None = None) -> str:
    if stat_result is None:
        try:
            stat_result = path.stat()
        except OSError:
            return ""
    return datetime.fromtimestamp(stat_result.st_mtime, tz=timezone.utc).isoformat()


def _subagent_meta(directory: Path) -> dict[str, Any]:
    """Describe a spawned subagent run directory (``<id>/meta.json``)."""
    info: dict[str, Any] = {
        "name": directory.name,
        "file": f"{directory.name}/",
        "ext": "[dir]",
        "size": _dir_entry_count(directory),
        "modified": _mtime_iso(directory),
    }
    for candidate in ("meta.json", "summary.json"):
        data = _read_json_dict(directory / candidate)
        if data is None:
            continue
        info["id"] = str(data.get("id") or directory.name)
        info["name"] = str(data.get("name") or directory.name)
        info["status"] = str(data.get("status") or "")
        info["cmd"] = str(data.get("cmd") or "")[:200]
        if data.get("created"):
            info["created"] = str(data["created"])
        if data.get("exit") is not None:
            info["exit"] = data["exit"]
        break
    return info


def list_subagents(subagents_dir: Path) -> dict[str, Any]:
    """List subagents.

    Two on-disk shapes are supported:
    * run directories written by ``bin/subagent.py`` (``<id>/meta.json``);
    * flat descriptor files, matching the allowlist used by list_agents/list_hooks.

    Placeholders such as ``.gitkeep`` and other dotfiles are never inventory.
    """
    subagents: list[dict[str, Any]] = []
    if not subagents_dir.exists():
        return {"ok": True, "count": 0, "subagents": []}
    for path in sorted(subagents_dir.iterdir()):
        if path.name.startswith("."):
            continue
        if path.is_dir():
            subagents.append(_subagent_meta(path))
            continue
        if not path.is_file() or path.suffix not in SUBAGENT_FILE_SUFFIXES:
            continue
        stat_result = path.stat()
        info: dict[str, Any] = {
            "name": path.stem,
            "file": path.name,
            "ext": path.suffix,
            "size": stat_result.st_size,
            "modified": _mtime_iso(path, stat_result),
        }
        if path.suffix == ".json":
            data = _read_json_dict(path)
            if data is not None:
                info["status"] = str(data.get("status") or "")
                info["cmd"] = str(data.get("cmd") or "")[:200]
        subagents.append(info)
    return {"ok": True, "count": len(subagents), "subagents": subagents}
