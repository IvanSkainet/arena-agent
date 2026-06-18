"""MCP memory export/import tools: memory.export and memory.import.

memory.export — export all memory facts as JSONL text. Returns the full
                export as text content.

memory.import — import memory facts from JSONL text. Each line is a JSON
                object with key, value, tags, timestamp. Existing keys
                are updated, new keys are inserted.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from arena.mcp.tool_utils import text_content


def handle_memory_export_import_tool(name: str, args: dict[str, Any], *, ctx) -> dict[str, Any] | None:
    """Handle memory.export and memory.import MCP tools."""
    if name not in {"memory.export", "memory.import"}:
        return None

    db_path = _get_db_path(ctx)
    if db_path is None:
        return {"isError": True, "content": [{"type": "text", "text": "ERROR: memory database path not available"}]}

    if name == "memory.export":
        return _handle_export(db_path)
    if name == "memory.import":
        return _handle_import(db_path, args)
    return None


def _get_db_path(ctx) -> Path | None:
    """Get the memory database path from the context."""
    # Try common attribute names
    for attr in ("memory_db_path", "db_path", "facts_db"):
        val = getattr(ctx, attr, None)
        if val:
            return Path(val)
    # Try via app_config
    try:
        cfg = ctx.app_config()
        if "memory_db" in cfg:
            return Path(cfg["memory_db"])
        if "root" in cfg:
            return Path(cfg["root"]) / "arena-bridge" / "memory" / "facts.db"
    except Exception:
        pass
    # Fallback: default location
    return Path.home() / "arena-bridge" / "memory" / "facts.db"


def _handle_export(db_path: Path) -> dict[str, Any]:
    """Export all memory facts as JSONL."""
    if not db_path.exists():
        return text_content("[]")  # empty export

    try:
        with sqlite3.connect(db_path) as conn:
            conn.row_factory = sqlite3.Row
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
    """Import memory facts from JSONL text."""
    data = args.get("data", args.get("content", ""))
    overwrite = bool(args.get("overwrite", False))

    if not data:
        return {"isError": True, "content": [{"type": "text", "text": "ERROR: missing 'data' argument (JSONL text)"}]}

    # Parse JSONL
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
            entries.append({
                "key": str(entry["key"]),
                "value": str(entry.get("value", "")),
                "tags": entry.get("tags", []) if isinstance(entry.get("tags"), list) else [],
                "timestamp": str(entry.get("timestamp", "")),
            })
        except json.JSONDecodeError as e:
            errors.append(f"line {i}: invalid JSON: {e}")

    if not entries and errors:
        return {"isError": True, "content": [{"type": "text", "text": f"ERROR: no valid entries. Errors:\n" + "\n".join(errors[:10])}]}

    # Write to database
    try:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(db_path) as conn:
            if overwrite:
                conn.execute("DELETE FROM memory_facts")
            for entry in entries:
                conn.execute('''
                    INSERT INTO memory_facts (key, value, tags, timestamp)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(key) DO UPDATE SET
                        value=excluded.value,
                        tags=excluded.tags,
                        timestamp=excluded.timestamp
                ''', (entry["key"], entry["value"], json.dumps(entry["tags"]), entry["timestamp"]))
            conn.commit()
    except sqlite3.Error as e:
        return {"isError": True, "content": [{"type": "text", "text": f"ERROR: database error: {e}"}]}

    result = f"imported {len(entries)} fact(s)"
    if errors:
        result += f" ({len(errors)} error(s) skipped)"
    if overwrite:
        result += " [overwrite mode: existing facts were replaced]"
    return text_content(result)
