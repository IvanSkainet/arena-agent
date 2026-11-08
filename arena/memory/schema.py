"""SQLite schema and migration helpers for memory facts."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Callable

from arena.memory.profiles import DEFAULT_MEMORY_PROFILE, normalize_memory_profile


def init_memory_db(*, db_path: Path, jsonl_path: Path, log_error: Callable[..., None] | None = None) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as conn:
        _ensure_memory_schema(conn)
        _rebuild_memory_fts(conn)
    migrate_jsonl_facts(db_path=db_path, jsonl_path=jsonl_path, log_error=log_error)


def _ensure_memory_schema(conn: sqlite3.Connection) -> None:
    table_exists = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='memory_facts'"
    ).fetchone()
    if not table_exists:
        conn.execute(
            """
            CREATE TABLE memory_facts (
                profile TEXT NOT NULL,
                key TEXT NOT NULL,
                value TEXT,
                tags TEXT,
                timestamp TEXT,
                PRIMARY KEY (profile, key)
            )
            """
        )
        return

    cols = [row[1] for row in conn.execute("PRAGMA table_info(memory_facts)").fetchall()]
    if "profile" in cols:
        return

    _drop_memory_fts_objects(conn)
    conn.execute("ALTER TABLE memory_facts RENAME TO memory_facts_legacy")
    conn.execute(
        """
        CREATE TABLE memory_facts (
            profile TEXT NOT NULL,
            key TEXT NOT NULL,
            value TEXT,
            tags TEXT,
            timestamp TEXT,
            PRIMARY KEY (profile, key)
        )
        """
    )
    conn.execute(
        """
        INSERT INTO memory_facts (profile, key, value, tags, timestamp)
        SELECT ?, key, value, tags, timestamp FROM memory_facts_legacy
        """,
        (DEFAULT_MEMORY_PROFILE,),
    )
    conn.execute("DROP TABLE memory_facts_legacy")


def _drop_memory_fts_objects(conn: sqlite3.Connection) -> None:
    conn.execute("DROP TRIGGER IF EXISTS memory_facts_ai")
    conn.execute("DROP TRIGGER IF EXISTS memory_facts_ad")
    conn.execute("DROP TRIGGER IF EXISTS memory_facts_au")
    conn.execute("DROP TABLE IF EXISTS memory_fts")



def _rebuild_memory_fts(conn: sqlite3.Connection) -> None:
    _drop_memory_fts_objects(conn)
    conn.execute(
        """
        CREATE VIRTUAL TABLE memory_fts USING fts5(
            profile, key, value, tags, content=memory_facts, content_rowid=rowid, tokenize="trigram"
        )
        """
    )
    conn.executescript(
        """
        CREATE TRIGGER memory_facts_ai AFTER INSERT ON memory_facts BEGIN
            INSERT INTO memory_fts(rowid, profile, key, value, tags)
            VALUES (new.rowid, new.profile, new.key, new.value, new.tags);
        END;
        CREATE TRIGGER memory_facts_ad AFTER DELETE ON memory_facts BEGIN
            INSERT INTO memory_fts(memory_fts, rowid, profile, key, value, tags)
            VALUES ('delete', old.rowid, old.profile, old.key, old.value, old.tags);
        END;
        CREATE TRIGGER memory_facts_au AFTER UPDATE ON memory_facts BEGIN
            INSERT INTO memory_fts(memory_fts, rowid, profile, key, value, tags)
            VALUES ('delete', old.rowid, old.profile, old.key, old.value, old.tags);
            INSERT INTO memory_fts(rowid, profile, key, value, tags)
            VALUES (new.rowid, new.profile, new.key, new.value, new.tags);
        END;
        """
    )
    conn.execute(
        """
        INSERT INTO memory_fts(rowid, profile, key, value, tags)
        SELECT rowid, profile, key, value, tags FROM memory_facts
        """
    )



def migrate_jsonl_facts(*, db_path: Path, jsonl_path: Path, log_error: Callable[..., None] | None = None) -> None:
    """Import facts appended to ``facts.jsonl`` since the last import.

    The JSONL file is a *live* writer's target, not only a legacy format:
    ``scripts/agent_helpers.py put`` still appends to it. The first version of
    this function read the file once and then renamed it to
    ``facts.jsonl.migrated``, which made the migration permanent -- every fact
    that script wrote afterwards was invisible to ``GET /v1/memory`` forever,
    while the script kept answering ``ok``.

    So the import is incremental instead of one-shot: a byte offset is kept next
    to the file, only complete lines past that offset are read, and the offset
    advances by exactly what was consumed. A trailing partial line (a writer
    killed mid-append) stays unread until it is finished, and a file that shrank
    -- rotated or truncated by the operator -- resets the offset to zero.
    """
    if not jsonl_path.exists():
        return
    offset_path = jsonl_path.with_name(jsonl_path.name + ".offset")
    start = _read_offset(offset_path)
    try:
        size = jsonl_path.stat().st_size
    except OSError:
        return
    if start > size:  # the file was rotated or truncated under us
        start = 0
    if start == size:
        return
    payload, consumed = _read_complete_lines(jsonl_path, start)
    if not payload:
        return
    with sqlite3.connect(db_path) as conn:
        try:
            for line in payload.splitlines():
                _import_jsonl_line(conn, line)
            conn.commit()
        except Exception as exc:  # noqa: BLE001 - a bad writer must not stop startup
            if log_error:
                log_error("[Memory] Failed to migrate facts: %s", exc)
            return
    _write_offset(offset_path, start + consumed, log_error)


def _read_offset(offset_path: Path) -> int:
    try:
        return max(0, int(offset_path.read_text(encoding="utf-8").strip() or "0"))
    except (OSError, ValueError):
        return 0


def _write_offset(offset_path: Path, value: int, log_error: Callable[..., None] | None) -> None:
    try:
        offset_path.write_text(str(value), encoding="utf-8")
    except OSError as exc:
        if log_error:
            log_error("[Memory] Could not record the facts.jsonl offset (%s); "
                      "the same lines will be re-imported next start", exc)


def _read_complete_lines(jsonl_path: Path, start: int) -> tuple[str, int]:
    """Bytes from ``start`` up to and including the last newline, plus its length."""
    try:
        with open(jsonl_path, "rb") as handle:
            handle.seek(start)
            chunk = handle.read()
    except OSError:
        return "", 0
    cut = chunk.rfind(b"\n") + 1
    if cut <= 0:
        return "", 0
    return chunk[:cut].decode("utf-8", "replace"), cut


def _import_jsonl_line(conn: sqlite3.Connection, line: str) -> None:
    line = line.strip()
    if not line:
        return
    try:
        item = json.loads(line)
    except json.JSONDecodeError:
        return  # a torn line is skipped, never fatal: the rest of the file is good
    conn.execute(
        """
        INSERT INTO memory_facts (profile, key, value, tags, timestamp)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(profile, key) DO UPDATE SET
            value=excluded.value,
            tags=excluded.tags,
            timestamp=excluded.timestamp
        """,
        (
            normalize_memory_profile(item.get("profile")),
            item.get("key", ""),
            item.get("value", ""),
            json.dumps(item.get("tags", [])),
            item.get("timestamp", ""),
        ),
    )
