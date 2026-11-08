"""SQLite schema and migration helpers for memory facts."""
from __future__ import annotations

import json
import os
import sqlite3
import tempfile
from contextlib import closing
from pathlib import Path
from typing import Callable

from arena.memory.profiles import DEFAULT_MEMORY_PROFILE, normalize_memory_profile


def init_memory_db(*, db_path: Path, jsonl_path: Path, log_error: Callable[..., None] | None = None) -> None:
    """Open (and, if needed, create) the facts database.

    A malformed file used to be terminal: this runs while the application is
    being assembled, so `sqlite3.DatabaseError` propagated out of `serve` and
    the whole bridge -- 536 routes, health, the dashboard -- refused to start,
    with a bare traceback that named neither the file nor a way out. Every
    other state file degrades instead: a truncated `mission.json` or a corrupt
    `queue/done/*.json` is skipped and the bridge starts.

    So corruption is handled the way the rest of the state layer handles it:
    the bytes are moved aside (never deleted -- they may be the only copy of
    the operator's facts) and a fresh database is created. If even that fails,
    the original error is raised, because at that point there is nothing left
    to degrade to.
    """
    db_path.parent.mkdir(parents=True, exist_ok=True)
    marker = _recovery_marker(db_path)
    if marker.exists():
        raise RuntimeError(
            f"Memory recovery is incomplete ({marker}); inspect the quarantined database "
            "and sidecars before removing the marker"
        )
    try:
        _prepare_memory_db(db_path)
    except sqlite3.DatabaseError as exc:
        # Locking, I/O, full disk and unsupported features are not corruption.
        # Moving a healthy database on those errors would lose live state.
        if not _is_corruption_error(exc):
            raise
        quarantined = _quarantine_db(db_path, exc, log_error)
        if quarantined is None:
            raise
        # SQLite otherwise creates the replacement using the process umask,
        # which can make sensitive facts world-readable on POSIX systems.
        fd = os.open(db_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        os.close(fd)
        _prepare_memory_db(db_path)
    migrate_jsonl_facts(db_path=db_path, jsonl_path=jsonl_path, log_error=log_error)


def _is_corruption_error(exc: sqlite3.DatabaseError) -> bool:
    """Fail closed except for SQLite's corruption codes or exact legacy messages.

    Python 3.10 does not expose sqlite_errorcode on exceptions. In that case
    accept only the two canonical SQLite messages and the plain DatabaseError
    type, not OperationalError or loosely matched text. When a code is present,
    it always takes precedence over the message.
    """
    code = getattr(exc, "sqlite_errorcode", None)
    if isinstance(code, int):
        return (code & 0xff) in (
            getattr(sqlite3, "SQLITE_CORRUPT", 11),
            getattr(sqlite3, "SQLITE_NOTADB", 26),
        )
    return type(exc) is sqlite3.DatabaseError and str(exc) in (
        "database disk image is malformed",
        "file is not a database",
    )


def _prepare_memory_db(db_path: Path) -> None:
    # sqlite3's context manager commits/rolls back but does not close the
    # connection. A Windows rename cannot quarantine the file while that
    # connection remains held by the exception traceback.
    with closing(sqlite3.connect(db_path)) as conn, conn:
        _ensure_memory_schema(conn)
        _rebuild_memory_fts(conn)


def _recovery_marker(db_path: Path) -> Path:
    return db_path.with_name(db_path.name + ".recovery-incomplete")


def _quarantine_db(
    db_path: Path,
    exc: sqlite3.DatabaseError,
    log_error: Callable[..., None] | None,
) -> Path | None:
    """Move an unreadable database and its sidecars aside, retaining failures.

    The marker survives a crash or a partial move. Subsequent startup must not
    open or create the database while a sidecar remains at its original name.
    """
    marker = _recovery_marker(db_path)
    try:
        fd = os.open(marker, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except OSError as marker_error:
        if log_error:
            log_error("[Memory] Cannot reserve recovery marker %s: %s", marker, marker_error)
        return None
    # Atomically reserve a private directory so neither the main file nor a
    # sidecar can overwrite a previous quarantine, even on a name collision.
    try:
        quarantine_dir = Path(tempfile.mkdtemp(prefix=f"{db_path.name}.corrupt-", dir=db_path.parent))
    except OSError:
        os.close(fd)
        marker.unlink()
        raise
    target = quarantine_dir / db_path.name
    # Record the intended destination before moving any data. If interrupted,
    # keep the marker even if writing or syncing it fails.
    with os.fdopen(fd, "w", encoding="utf-8") as marker_file:
        marker_file.write(f"source: {db_path}\nquarantine: {target}\n")
        marker_file.flush()
        os.fsync(marker_file.fileno())
    try:
        os.replace(db_path, target)
    except OSError as move_error:
        # The source was not moved; no sidecars have been touched.
        quarantine_dir.rmdir()
        marker.unlink()
        if log_error:
            log_error(
                "[Memory] Database at %s is unreadable (%s) and could not be moved aside (%s); "
                "the bridge cannot start until it is repaired or removed by hand",
                db_path, exc, move_error,
            )
        return None
    try:
        for suffix in ("-wal", "-shm"):
            sidecar = db_path.with_name(db_path.name + suffix)
            if sidecar.exists():
                os.replace(sidecar, target.with_name(target.name + suffix))
    except OSError as move_error:
        if log_error:
            log_error(
                "[Memory] Quarantine incomplete for %s: %s. Marker %s blocks restart; "
                "inspect %s and the original sidecars before clearing it",
                db_path, move_error, marker, target,
            )
        raise
    marker.unlink()
    if log_error:
        log_error(
            "[Memory] Database at %s was unreadable (%s); it was moved to %s and a fresh one "
            "will be created; the moved database and sidecars may contain previous facts",
            db_path, exc, target,
        )
    return target


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
                        profile = normalize_memory_profile(item.get("profile"))
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
                                profile,
                                item.get("key", ""),
                                item.get("value", ""),
                                json.dumps(item.get("tags", [])),
                                item.get("timestamp", ""),
                            ),
                        )
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
