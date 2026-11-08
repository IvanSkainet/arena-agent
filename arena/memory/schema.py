"""SQLite schema and migration helpers for memory facts."""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from contextlib import closing
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
    """Import complete JSONL records with a transactional checkpoint.

    The offset and digest live in SQLite alongside the facts. A write lock is
    acquired *before* inspecting either the checkpoint or source, so two
    bridge processes cannot replay stale data or commit a stale checkpoint.
    The hash detects in-place truncation or replacement even when the new
    file is the same size or larger. An incomplete final line stays pending.
    """
    if not jsonl_path.exists():
        return
    try:
        with closing(sqlite3.connect(db_path, timeout=30)) as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                "CREATE TABLE IF NOT EXISTS memory_jsonl_checkpoint "
                "(source TEXT PRIMARY KEY, offset INTEGER NOT NULL, prefix_hash TEXT NOT NULL)"
            )
            source = str(jsonl_path.resolve())
            row = conn.execute(
                "SELECT offset, prefix_hash FROM memory_jsonl_checkpoint WHERE source = ?", (source,)
            ).fetchone()
            start, digest = (int(row[0]), str(row[1])) if row else (0, "")
            snapshot = _stable_jsonl_read(jsonl_path, start, digest)
            if snapshot is None:
                conn.rollback()
                return  # source changed during the read; retry on the next start
            payload, offset, prefix_hash = snapshot
            for line in payload.decode("utf-8", "replace").split("\n"):
                _import_jsonl_line(conn, line)
            conn.execute(
                "INSERT INTO memory_jsonl_checkpoint(source, offset, prefix_hash) VALUES (?, ?, ?) "
                "ON CONFLICT(source) DO UPDATE SET offset=excluded.offset, prefix_hash=excluded.prefix_hash",
                (source, offset, prefix_hash),
            )
            conn.commit()
    except (OSError, sqlite3.Error, ValueError, TypeError) as exc:
        if log_error:
            log_error("[Memory] Failed to migrate facts: %s", exc)


def _stable_jsonl_read(jsonl_path: Path, start: int, expected_hash: str) -> tuple[bytes, int, str] | None:
    """Read complete records from a consistent snapshot, validating its prefix."""
    with jsonl_path.open("rb") as handle:
        before = os.fstat(handle.fileno())
        hasher = hashlib.sha256()
        remaining = start if 0 <= start <= before.st_size else 0
        while remaining:
            chunk = handle.read(min(remaining, 1024 * 1024))
            if not chunk:
                return None
            hasher.update(chunk)
            remaining -= len(chunk)
        if start > before.st_size or start < 0 or (start and hasher.hexdigest() != expected_hash):
            start = 0
            handle.seek(0)
            hasher = hashlib.sha256()
        data = handle.read()
        after = os.fstat(handle.fileno())
        current = jsonl_path.stat()
        def signature(st):
            return st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns
        if signature(before) != signature(after) or signature(after) != signature(current):
            return None
    cut = data.rfind(b"\n") + 1
    payload = data[:cut]
    hasher.update(payload)
    return payload, start + cut, hasher.hexdigest()


def _import_jsonl_line(conn: sqlite3.Connection, line: str) -> None:
    line = line.strip()
    if not line:
        return
    try:
        item = json.loads(line)
    except json.JSONDecodeError:
        return  # a torn line is skipped, never fatal: the rest of the file is good
    if not isinstance(item, dict):
        return  # valid JSON scalars and arrays are not fact records
    if any(not isinstance(item.get(field), (str, int, float, type(None)))
           for field in ("key", "value", "timestamp", "ts")):
        return  # JSON arrays/objects are not valid SQLite scalar bindings
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
            item.get("timestamp", item.get("ts", "")),
        ),
    )
