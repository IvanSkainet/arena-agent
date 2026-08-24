"""Resource listing/show helpers."""
from __future__ import annotations

import json
import logging
import os
from collections.abc import Iterator
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from arena.resources.mission_catalog import summarize_mission_dir
from arena.resources.mission_identifier import resolve_mission_name

logger = logging.getLogger(__name__)


def _classify(path: Path, resolved_root: Path) -> tuple[bool, str]:
    """Return (contained, reason) for *path* against an already-resolved root.

    The two failure modes are kept apart on purpose. "Escaped" is a finding
    worth a warning; "gone" is a broken link or an entry unlinked between
    `iterdir()` and `resolve()`, which is ordinary and must not be reported as
    an attempted escape -- a log that cries escape at every stale link teaches
    the reader to ignore it.
    """
    try:
        resolved = path.resolve(strict=True)
    except FileNotFoundError:
        return False, "gone"
    except (OSError, RuntimeError, ValueError):
        # RuntimeError: symlink loop. ValueError: unrelated drive on Windows.
        # OSError also covers ELOOP, which some platforms raise instead.
        return False, "unresolvable"
    if resolved.is_relative_to(resolved_root):
        return True, "ok"
    return False, "escaped"


def _is_contained(path: Path, resolved_root: Path) -> bool:
    """True when *path* really lives under *resolved_root*.

    `Path.is_file()`/`is_dir()` follow symlinks, so a link planted in a
    resource directory is listed as a genuine local entry and, for `.json`
    descriptors, its fields are parsed out of wherever it points and returned
    by the API. The full `resolve()` is what does the work here: checking
    `is_symlink()` on the entry is not enough, because when the *directory*
    being scanned is itself a link out of the root (`reports/shots`), its
    entries are ordinary files whose real location is still outside.

    `strict=True` also drops broken links, which cannot be inventory either.

    Known limit -- TOCTOU. Containment is checked, then the caller reads or
    stats the path in a separate syscall, so an attacker who can swap the
    entry in between can still be read. Closing that would need
    descriptor-relative operations with `O_NOFOLLOW`, which do not carry to
    Windows, and it buys nothing here: planting the symlink already requires
    write access to the agent's own home directory, and anyone holding it can
    write a real descriptor file with arbitrary contents instead. This guard
    is about inventory integrity, not about defending a directory an attacker
    can already write to.
    """
    return _classify(path, resolved_root)[0]


def _contained_child(directory: Path, name: str, resolved_root: Path) -> Path | None:
    """Return ``directory/name`` when it exists and stays inside the root.

    Containment of the directory entry says nothing about what is *inside* it:
    a legitimately contained mission or run directory can hold a `mission.json`
    or `meta.json` that is itself a link out of the tree. Demonstrated on the
    first revision of this fix -- a contained `missions/contained/` whose
    `mission.json` pointed outside returned `id`, `name` and `goal` from the
    linked file, and a `subagents/run1/meta.json` link returned
    `status="PWNED"` and `cmd="rm -rf /"`. The escape simply moved one level
    deeper than the check.
    """
    child = directory / name
    if not child.exists():
        return None
    contained, reason = _classify(child, resolved_root)
    if contained:
        return child
    if reason == "escaped":
        logger.warning(
            "[resources] ignoring %s: resolves outside the resource root %s",
            child, resolved_root,
        )
    else:
        logger.debug("[resources] ignoring %s: %s", child, reason)
    return None


def _contained_entries(directory: Path, root: Path) -> Iterator[Path]:
    """Yield sorted entries of *directory* that resolve inside *root*.

    A symlink pointing back inside the same root stays legal: that is a local
    reorganisation, not an escape. The root is resolved once per listing
    rather than once per entry -- measured at ~38ms per 3000 entries for the
    per-entry `resolve()`, against ~12ms for a bare `lstat`, which is the
    price of the guarantee.
    """
    try:
        resolved_root = root.resolve(strict=True)
    except (OSError, RuntimeError, ValueError):
        logger.warning("[resources] listing root is unresolvable, skipped: %s", root)
        return
    try:
        entries = sorted(directory.iterdir())
    except OSError as exc:
        logger.warning("[resources] cannot read %s: %s", directory, exc)
        return
    for path in entries:
        contained, reason = _classify(path, resolved_root)
        if contained:
            yield path
        elif reason == "gone":
            # A broken link or an entry unlinked mid-scan: not an escape.
            logger.debug("[resources] skipping %s: no longer resolvable", path)
        elif reason == "unresolvable":
            # A symlink loop or a drive mismatch: containment was never
            # established either way, so calling it an escape would be a
            # guess stated as a fact.
            logger.warning("[resources] skipping %s: path is unresolvable", path)
        else:
            # Skipped entries used to vanish without trace; an inventory that
            # silently drops things is its own kind of wrong answer.
            logger.warning(
                "[resources] skipping %s: resolves outside the resource root %s",
                path, resolved_root,
            )


def list_missions(missions_dir: Path) -> list[dict[str, Any]]:
    missions: list[dict[str, Any]] = []
    if missions_dir.exists():
        try:
            resolved_root = missions_dir.resolve(strict=True)
        except (OSError, RuntimeError, ValueError):
            return missions
        for path in _contained_entries(missions_dir, missions_dir):
            if path.is_file() and path.suffix in (".json", ".yaml", ".yml", ".md", ".txt"):
                missions.append({"name": path.stem, "ext": path.suffix, "size": path.stat().st_size, "modified": datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat()})
            elif path.is_dir():
                if _contained_child(path, "mission.json", resolved_root) is not None:
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

    #120: the name guard rejects `..` and separators, but not a symlink
    already sitting in the missions directory. This reader is the worst of
    the six affected paths -- the listers surface selected fields, while this
    one returns the *whole* file -- so containment is checked here too.
    """
    if ".." in name or "/" in name or "\\" in name or name.startswith("."):
        return {"ok": False, "error": "invalid mission name"}
    name = resolve_mission_name(missions_dir, name)
    try:
        resolved_root = missions_dir.resolve(strict=True)
    except (OSError, RuntimeError, ValueError):
        return {"ok": False, "error": f"mission '{name}' not found"}
    for ext in ("", ".json", ".yaml", ".yml", ".md", ".txt"):
        path = missions_dir / f"{name}{ext}"
        if not path.exists() or not path.is_file():
            continue
        contained, reason = _classify(path, resolved_root)
        if not contained:
            # A refusal that leaves no trace is indistinguishable from the
            # file simply not being there.
            if reason == "escaped":
                logger.warning(
                    "[resources] refusing mission %r: %s resolves outside %s",
                    name, path, resolved_root,
                )
            continue
        if True:
            content = path.read_text(encoding="utf-8", errors="replace")
            return {"ok": True, "name": name, "file": str(path), "ext": path.suffix or ext, "content": content, "size": path.stat().st_size}
    directory = missions_dir / name
    if directory.exists() and directory.is_dir():
        contained, reason = _classify(directory, resolved_root)
        if not contained and reason == "escaped":
            logger.warning(
                "[resources] refusing mission directory %r: %s resolves outside %s",
                name, directory, resolved_root,
            )
    else:
        contained = False
    if contained:
        files = []
        for item in _contained_entries(directory, resolved_root):
            files.append({"name": item.name, "size": item.stat().st_size if item.is_file() else 0, "is_dir": item.is_dir()})
        payload: dict[str, Any] = {"ok": True, "name": name, "is_dir": True, "files": files}
        if _contained_child(directory, "mission.json", resolved_root) is not None:
            payload["mission"] = summarize_mission_dir(directory)
        return payload
    return {"ok": False, "error": f"mission '{name}' not found"}


def list_reports(reports_dir: Path) -> list[dict[str, Any]]:
    reports: list[dict[str, Any]] = []
    if reports_dir.exists():
        for path in _contained_entries(reports_dir, reports_dir):
            if path.is_file():
                reports.append({"name": path.name, "size": path.stat().st_size, "modified": datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat()})
    shots_dir = reports_dir / "shots"
    if shots_dir.exists():
        # Rooted at reports_dir, not shots_dir: `shots` may itself be a link
        # out of the tree, and then its ordinary files are outside too.
        for path in _contained_entries(shots_dir, reports_dir):
            if path.is_file():
                reports.append({"name": f"shots/{path.name}", "size": path.stat().st_size, "modified": datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat()})
    return reports


def list_hooks(hooks_dir: Path) -> dict[str, Any]:
    hooks: list[dict[str, Any]] = []
    if not hooks_dir.exists():
        return {"ok": True, "count": 0, "hooks": []}
    for path in _contained_entries(hooks_dir, hooks_dir):
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
    for path in _contained_entries(agents_dir, agents_dir):
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


def _subagent_meta(directory: Path, resolved_root: Path | None = None) -> dict[str, Any]:
    """Describe a spawned subagent run directory (``<id>/meta.json``)."""
    info: dict[str, Any] = {
        "name": directory.name,
        "file": f"{directory.name}/",
        "ext": "[dir]",
        "size": _dir_entry_count(directory),
        "modified": _mtime_iso(directory),
    }
    for candidate in ("meta.json", "summary.json"):
        if resolved_root is None:
            descriptor: Path | None = directory / candidate
        else:
            descriptor = _contained_child(directory, candidate, resolved_root)
        if descriptor is None:
            continue
        data = _read_json_dict(descriptor)
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
    try:
        resolved_root = subagents_dir.resolve(strict=True)
    except (OSError, RuntimeError, ValueError):
        return {"ok": True, "count": 0, "subagents": []}
    for path in _contained_entries(subagents_dir, subagents_dir):
        if path.name.startswith("."):
            continue
        if path.is_dir():
            subagents.append(_subagent_meta(path, resolved_root))
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
