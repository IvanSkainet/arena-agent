"""MCP memory export/import tools."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from arena.memory.profiles import DEFAULT_MEMORY_PROFILE, normalize_memory_profile, normalize_memory_profile_filter, validate_memory_profile
from arena.mcp.tool_utils import text_content


def handle_memory_export_import_tool(name: str, args: dict[str, Any], *, ctx) -> dict[str, Any] | None:
    if name not in {"memory.export", "memory.import"}:
        return None

    db_path = _get_db_path(ctx)
    if db_path is None:
        return {"isError": True, "content": [{"type": "text", "text": "ERROR: memory database path not available"}]}

    if name == "memory.export":
        return _handle_export(db_path, args)
    if name == "memory.import":
        return _handle_import(db_path, args)
    return None


def _get_db_path(ctx) -> Path | None:
    for attr in ("memory_db_path", "db_path", "facts_db"):
        val = getattr(ctx, attr, None)
        if val:
            return Path(val)
    try:
        cfg = ctx.app_config()
        if "memory_db" in cfg:
            return Path(cfg["memory_db"])
        if "root" in cfg:
            return Path(cfg["root"]) / "arena-bridge" / "memory" / "facts.db"
    except Exception:
        pass
    return Path.home() / "arena-bridge" / "memory" / "facts.db"


def _db_has_profile_column(conn: sqlite3.Connection) -> bool:
    cols = [row[1] for row in conn.execute("PRAGMA table_info(memory_facts)").fetchall()]
    return "profile" in cols


def _handle_export(db_path: Path, args: dict[str, Any]) -> dict[str, Any]:
    if not db_path.exists():
        return text_content("[]")
    profile_arg = args.get("profile")
    profile_err = validate_memory_profile(profile_arg, allow_all=True)
    if profile_err:
        return {"isError": True, "content": [{"type": "text", "text": f"ERROR: {profile_err}"}]}
    profile = None if profile_arg is None else normalize_memory_profile_filter(profile_arg)

    try:
        with sqlite3.connect(db_path) as conn:
            conn.row_factory = sqlite3.Row
            has_profile = _db_has_profile_column(conn)
            if has_profile:
                if profile is None:
                    rows = conn.execute(
                        "SELECT profile, key, value, tags, timestamp FROM memory_facts ORDER BY timestamp ASC"
                    ).fetchall()
                else:
                    rows = conn.execute(
                        "SELECT profile, key, value, tags, timestamp FROM memory_facts WHERE profile = ? ORDER BY timestamp ASC",
                        (profile,),
                    ).fetchall()
            else:
                rows = conn.execute("SELECT key, value, tags, timestamp FROM memory_facts ORDER BY timestamp ASC").fetchall()
    except sqlite3.Error as e:
        return {"isError": True, "content": [{"type": "text", "text": f"ERROR: database error: {e}"}]}

    lines = []
    for row in rows:
        try:
            tags = json.loads(row["tags"]) if row["tags"] else []
        except (json.JSONDecodeError, TypeError):
            tags = []
        entry = {
            "profile": row["profile"] if "profile" in row.keys() else DEFAULT_MEMORY_PROFILE,
            "key": row["key"],
            "value": row["value"],
            "tags": tags,
            "timestamp": row["timestamp"],
        }
        lines.append(json.dumps(entry, ensure_ascii=False))
    if not lines:
        return text_content("[]")
    return text_content("\n".join(lines))


def _handle_import(db_path: Path, args: dict[str, Any]) -> dict[str, Any]:
    data = args.get("data", args.get("content", ""))
    overwrite = bool(args.get("overwrite", False))
    profile_err = validate_memory_profile(args.get("profile"), allow_all=False)
    if profile_err:
        return {"isError": True, "content": [{"type": "text", "text": f"ERROR: {profile_err}"}]}
    explicit_profile = args.get("profile")
    default_profile = normalize_memory_profile(explicit_profile)

    if not data:
        return {"isError": True, "content": [{"type": "text", "text": "ERROR: missing 'data' argument (JSONL text)"}]}

    entries = []
    errors = []
    for i, line in enumerate(data.strip().split("\n"), 1):
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
            if not entry.get("key"):
                errors.append(f"line {i}: missing 'key'")
                continue
            entry_profile = entry.get("profile", default_profile)
            err = validate_memory_profile(entry_profile)
            if err:
                errors.append(f"line {i}: {err}")
                continue
            entries.append(
                {
                    "profile": normalize_memory_profile(entry_profile),
                    "key": str(entry["key"]),
                    "value": str(entry.get("value", "")),
                    "tags": entry.get("tags", []) if isinstance(entry.get("tags"), list) else [],
                    "timestamp": str(entry.get("timestamp", "")),
                }
            )
        except json.JSONDecodeError as e:
            errors.append(f"line {i}: invalid JSON: {e}")

    if not entries and errors:
        return {"isError": True, "content": [{"type": "text", "text": "ERROR: no valid entries. Errors:\n" + "\n".join(errors[:10])}]}

    try:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(db_path) as conn:
            has_profile = _db_has_profile_column(conn)
            if overwrite:
                if has_profile:
                    if explicit_profile:
                        conn.execute("DELETE FROM memory_facts WHERE profile = ?", (default_profile,))
                    else:
                        profiles = sorted({entry["profile"] for entry in entries})
                        for profile_name in profiles:
                            conn.execute("DELETE FROM memory_facts WHERE profile = ?", (profile_name,))
                else:
                    conn.execute("DELETE FROM memory_facts")
            for entry in entries:
                if has_profile:
                    conn.execute(
                        """
                        INSERT INTO memory_facts (profile, key, value, tags, timestamp)
                        VALUES (?, ?, ?, ?, ?)
                        ON CONFLICT(profile, key) DO UPDATE SET
                            value=excluded.value,
                            tags=excluded.tags,
                            timestamp=excluded.timestamp
                        """,
                        (entry["profile"], entry["key"], entry["value"], json.dumps(entry["tags"]), entry["timestamp"]),
                    )
                else:
                    conn.execute(
                        """
                        INSERT INTO memory_facts (key, value, tags, timestamp)
                        VALUES (?, ?, ?, ?)
                        ON CONFLICT(key) DO UPDATE SET
                            value=excluded.value,
                            tags=excluded.tags,
                            timestamp=excluded.timestamp
                        """,
                        (entry["key"], entry["value"], json.dumps(entry["tags"]), entry["timestamp"]),
                    )
            conn.commit()
    except sqlite3.Error as e:
        return {"isError": True, "content": [{"type": "text", "text": f"ERROR: database error: {e}"}]}

    result = f"imported {len(entries)} fact(s)"
    if errors:
        result += f" ({len(errors)} error(s) skipped)"
    if overwrite:
        if explicit_profile:
            result += f" [overwrite mode: profile={default_profile}]"
        else:
            touched = ", ".join(sorted({entry['profile'] for entry in entries}))
            result += f" [overwrite mode: profiles={touched}]"
    return text_content(result)
