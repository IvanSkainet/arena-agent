"""SQLite schema, migration, and CRUD helpers for memory facts."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Callable


def init_memory_db(*, db_path: Path, jsonl_path: Path, log_error: Callable[..., None] | None = None) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as conn:
        conn.execute('''
        CREATE TABLE IF NOT EXISTS memory_facts (
            key TEXT PRIMARY KEY,
            value TEXT,
            tags TEXT,
            timestamp TEXT
        );
        ''')
        conn.execute('''
        CREATE VIRTUAL TABLE IF NOT EXISTS memory_fts USING fts5(
            key, value, tags, content=memory_facts, content_rowid=rowid, tokenize="trigram"
        );
        ''')
        conn.executescript('''
        CREATE TRIGGER IF NOT EXISTS memory_facts_ai AFTER INSERT ON memory_facts BEGIN
            INSERT INTO memory_fts(rowid, key, value, tags) VALUES (new.rowid, new.key, new.value, new.tags);
        END;
        CREATE TRIGGER IF NOT EXISTS memory_facts_ad AFTER DELETE ON memory_facts BEGIN
            INSERT INTO memory_fts(memory_fts, rowid, key, value, tags) VALUES ('delete', old.rowid, old.key, old.value, old.tags);
        END;
        CREATE TRIGGER IF NOT EXISTS memory_facts_au AFTER UPDATE ON memory_facts BEGIN
            INSERT INTO memory_fts(memory_fts, rowid, key, value, tags) VALUES ('delete', old.rowid, old.key, old.value, old.tags);
            INSERT INTO memory_fts(rowid, key, value, tags) VALUES (new.rowid, new.key, new.value, new.tags);
        END;
        ''')
    migrate_jsonl_facts(db_path=db_path, jsonl_path=jsonl_path, log_error=log_error)


def migrate_jsonl_facts(*, db_path: Path, jsonl_path: Path, log_error: Callable[..., None] | None = None) -> None:
    if not jsonl_path.exists():
        return
    migrated_path = jsonl_path.with_suffix(".jsonl.migrated")
    if migrated_path.exists():
        return
    with sqlite3.connect(db_path) as conn:
        try:
            with open(jsonl_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        item = json.loads(line)
                        write_fact_to_conn(conn, {
                            "key": item.get("key", ""),
                            "value": item.get("value", ""),
                            "tags": item.get("tags", []),
                            "timestamp": item.get("timestamp", ""),
                        })
                    except json.JSONDecodeError:
                        pass
            conn.commit()
        except Exception as e:
            if log_error:
                log_error("[Memory] Failed to migrate facts: %s", e)
    try:
        jsonl_path.rename(migrated_path)
    except OSError:
        pass


def row_to_fact(row) -> dict[str, Any]:
    try:
        tags = json.loads(row["tags"]) if row["tags"] else []
    except Exception:
        tags = []
    return {"key": row["key"], "value": row["value"], "tags": tags, "timestamp": row["timestamp"]}


def write_fact_to_conn(conn: sqlite3.Connection, entry: dict[str, Any]) -> None:
    conn.execute('''
    INSERT INTO memory_facts (key, value, tags, timestamp)
    VALUES (?, ?, ?, ?)
    ON CONFLICT(key) DO UPDATE SET
        value=excluded.value,
        tags=excluded.tags,
        timestamp=excluded.timestamp
    ''', (entry.get("key", ""), entry.get("value", ""), json.dumps(entry.get("tags", [])), entry.get("timestamp", "")))


def load_facts(db_path: Path) -> list[dict[str, Any]]:
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT key, value, tags, timestamp FROM memory_facts ORDER BY timestamp ASC").fetchall()
        return [row_to_fact(row) for row in rows]


def search_facts_paged(db_path: Path, q: str = "", offset: int = 0, limit: int = 100, log_error: Callable[..., None] | None = None) -> tuple[int, list[dict[str, Any]]]:
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        if q:
            safe_q = '"' + q.replace('"', '""') + '"'
            try:
                total = conn.execute("SELECT COUNT(*) FROM memory_fts WHERE memory_fts MATCH ?", (safe_q,)).fetchone()[0]
                rows = conn.execute('''
                    SELECT m.key, m.value, m.tags, m.timestamp
                    FROM memory_facts m
                    JOIN memory_fts f ON m.rowid = f.rowid
                    WHERE memory_fts MATCH ?
                    ORDER BY m.timestamp ASC
                    LIMIT ? OFFSET ?
                ''', (safe_q, limit, offset)).fetchall()
            except sqlite3.OperationalError as e:
                if log_error:
                    log_error("[Memory] SQLite FTS query error: %s", e)
                return 0, []
        else:
            total = conn.execute("SELECT COUNT(*) FROM memory_facts").fetchone()[0]
            rows = conn.execute("SELECT key, value, tags, timestamp FROM memory_facts ORDER BY timestamp ASC LIMIT ? OFFSET ?", (limit, offset)).fetchall()
        return total, [row_to_fact(row) for row in rows]


def write_fact(db_path: Path, entry: dict[str, Any]) -> None:
    with sqlite3.connect(db_path) as conn:
        write_fact_to_conn(conn, entry)
        conn.commit()


def delete_fact(db_path: Path, key: str) -> bool:
    with sqlite3.connect(db_path) as conn:
        cur = conn.execute("DELETE FROM memory_facts WHERE key = ?", (key,))
        conn.commit()
        return cur.rowcount > 0
