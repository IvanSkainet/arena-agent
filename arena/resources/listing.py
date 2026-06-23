"""Resource listing/show helpers."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from arena.resources.mission_catalog import summarize_mission_dir


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
    if ".." in name or "/" in name or "\\" in name or name.startswith("."):
        return {"ok": False, "error": "invalid mission name"}
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
        payload = {"ok": True, "name": name, "is_dir": True, "files": files}
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


def list_subagents(subagents_dir: Path) -> dict[str, Any]:
    subagents: list[dict[str, Any]] = []
    if not subagents_dir.exists():
        return {"ok": True, "count": 0, "subagents": []}
    for path in sorted(subagents_dir.iterdir()):
        if path.is_file():
            info: dict[str, Any] = {"name": path.stem, "file": path.name, "ext": path.suffix, "size": path.stat().st_size, "modified": datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat()}
            if path.suffix == ".json":
                try:
                    data = json.loads(path.read_text(encoding="utf-8"))
                    info["status"] = data.get("status", "")
                    info["cmd"] = data.get("cmd", "")[:200]
                except Exception:
                    pass
            subagents.append(info)
    return {"ok": True, "count": len(subagents), "subagents": subagents}
