"""SQLite CRUD helpers for memory facts."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Callable

from arena.memory.profiles import DEFAULT_MEMORY_PROFILE, normalize_memory_profile, normalize_memory_profile_filter


def row_to_fact(row) -> dict[str, Any]:
    try:
        tags = json.loads(row["tags"]) if row["tags"] else []
    except Exception:
        tags = []
    return {
        "profile": row["profile"],
        "key": row["key"],
        "value": row["value"],
        "tags": tags,
        "timestamp": row["timestamp"],
    }


def list_profiles(db_path: Path) -> list[str]:
    with sqlite3.connect(db_path) as conn:
        rows = conn.execute("SELECT DISTINCT profile FROM memory_facts ORDER BY profile ASC").fetchall()
    profiles = [row[0] for row in rows if row and row[0]]
    if DEFAULT_MEMORY_PROFILE in profiles:
        profiles.remove(DEFAULT_MEMORY_PROFILE)
        profiles.insert(0, DEFAULT_MEMORY_PROFILE)
    return profiles


def write_fact_to_conn(conn: sqlite3.Connection, entry: dict[str, Any]) -> None:
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
            normalize_memory_profile(entry.get("profile")),
            entry.get("key", ""),
            entry.get("value", ""),
            json.dumps(entry.get("tags", [])),
            entry.get("timestamp", ""),
        ),
    )


def load_facts(db_path: Path, profile: str | None = DEFAULT_MEMORY_PROFILE) -> list[dict[str, Any]]:
    profile_filter = None if profile is None else normalize_memory_profile_filter(profile)
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        if profile_filter is None:
            rows = conn.execute(
                "SELECT profile, key, value, tags, timestamp FROM memory_facts ORDER BY timestamp ASC"
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT profile, key, value, tags, timestamp FROM memory_facts WHERE profile = ? ORDER BY timestamp ASC",
                (profile_filter,),
            ).fetchall()
        return [row_to_fact(row) for row in rows]


def search_facts_paged(
    db_path: Path,
    q: str = "",
    offset: int = 0,
    limit: int = 100,
    log_error: Callable[..., None] | None = None,
    profile: str | None = DEFAULT_MEMORY_PROFILE,
) -> tuple[int, list[dict[str, Any]]]:
    profile_filter = None if profile is None else normalize_memory_profile_filter(profile)
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        if q:
            safe_q = '"' + q.replace('"', '""') + '"'
            try:
                if profile_filter is None:
                    total = conn.execute(
                        "SELECT COUNT(*) FROM memory_fts WHERE memory_fts MATCH ?",
                        (safe_q,),
                    ).fetchone()[0]
                    rows = conn.execute(
                        """
                        SELECT m.profile, m.key, m.value, m.tags, m.timestamp
                        FROM memory_facts m
                        JOIN memory_fts f ON m.rowid = f.rowid
                        WHERE memory_fts MATCH ?
                        ORDER BY m.timestamp ASC
                        LIMIT ? OFFSET ?
                        """,
                        (safe_q, limit, offset),
                    ).fetchall()
                else:
                    total = conn.execute(
                        "SELECT COUNT(*) FROM memory_fts WHERE profile = ? AND memory_fts MATCH ?",
                        (profile_filter, safe_q),
                    ).fetchone()[0]
                    rows = conn.execute(
                        """
                        SELECT m.profile, m.key, m.value, m.tags, m.timestamp
                        FROM memory_facts m
                        JOIN memory_fts f ON m.rowid = f.rowid
                        WHERE f.profile = ? AND memory_fts MATCH ?
                        ORDER BY m.timestamp ASC
                        LIMIT ? OFFSET ?
                        """,
                        (profile_filter, safe_q, limit, offset),
                    ).fetchall()
            except sqlite3.OperationalError as e:
                if log_error:
                    log_error("[Memory] SQLite FTS query error: %s", e)
                return 0, []
        else:
            if profile_filter is None:
                total = conn.execute("SELECT COUNT(*) FROM memory_facts").fetchone()[0]
                rows = conn.execute(
                    "SELECT profile, key, value, tags, timestamp FROM memory_facts ORDER BY timestamp ASC LIMIT ? OFFSET ?",
                    (limit, offset),
                ).fetchall()
            else:
                total = conn.execute(
                    "SELECT COUNT(*) FROM memory_facts WHERE profile = ?",
                    (profile_filter,),
                ).fetchone()[0]
                rows = conn.execute(
                    "SELECT profile, key, value, tags, timestamp FROM memory_facts WHERE profile = ? ORDER BY timestamp ASC LIMIT ? OFFSET ?",
                    (profile_filter, limit, offset),
                ).fetchall()
        return total, [row_to_fact(row) for row in rows]


def write_fact(db_path: Path, entry: dict[str, Any]) -> None:
    with sqlite3.connect(db_path) as conn:
        write_fact_to_conn(conn, entry)
        conn.commit()


def delete_fact(db_path: Path, key: str, profile: str | None = DEFAULT_MEMORY_PROFILE) -> bool:
    profile_name = normalize_memory_profile(profile)
    with sqlite3.connect(db_path) as conn:
        cur = conn.execute("DELETE FROM memory_facts WHERE profile = ? AND key = ?", (profile_name, key))
        conn.commit()
        return cur.rowcount > 0
