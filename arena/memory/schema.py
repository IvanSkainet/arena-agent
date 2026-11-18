"""SQLite schema and migration helpers for memory facts."""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import tempfile
from contextlib import closing
from pathlib import Path
from typing import Callable

from arena.memory.health import record_recovery
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
    db_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    db_path.parent.chmod(0o700)
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
        record_recovery(db_path, quarantined)
        marker.unlink()
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
    if db_path.is_symlink():
        raise OSError("refusing a symlink memory database")
    fd = os.open(db_path, os.O_WRONLY | os.O_CREAT, 0o600)
    os.close(fd)
    db_path.chmod(0o600)
    with closing(sqlite3.connect(db_path)) as conn, conn:
        _ensure_memory_schema(conn)
        _rebuild_memory_fts(conn)


def _recovery_marker(db_path: Path) -> Path:
    return db_path.with_name(db_path.name + ".recovery-incomplete")


def _reserve_quarantine(db_path: Path, marker: Path) -> Path:
    """Reserve a private destination and persist the recovery plan first."""
    fd = os.open(marker, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        directory = Path(tempfile.mkdtemp(prefix=f"{db_path.name}.corrupt-", dir=db_path.parent))
    except OSError:
        os.close(fd)
        marker.unlink()
        raise
    target = directory / db_path.name
    with os.fdopen(fd, "w", encoding="utf-8") as stream:
        stream.write(f"source: {db_path}\nquarantine: {target}\n")
        stream.flush()
        os.fsync(stream.fileno())
    return target


def _move_quarantine_main(db_path: Path, target: Path, marker: Path,
                          log_error: Callable[..., None] | None) -> bool:
    try:
        os.replace(db_path, target)
    except OSError as exc:
        target.parent.rmdir()
        marker.unlink()
        if log_error:
            log_error("[Memory] Cannot move unreadable database %s to %s: %s", db_path, target, exc)
        return False
    target.chmod(0o600)
    return True


def _move_quarantine_sidecars(db_path: Path, target: Path) -> None:
    for suffix in ("-wal", "-shm"):
        sidecar = db_path.with_name(db_path.name + suffix)
        if sidecar.exists():
            destination = target.with_name(target.name + suffix)
            os.replace(sidecar, destination)
            destination.chmod(0o600)


def _quarantine_db(
    db_path: Path,
    exc: sqlite3.DatabaseError,
    log_error: Callable[..., None] | None,
) -> Path | None:
    """Preserve corrupt bytes and WAL/SHM; leave a marker on partial recovery."""
    marker = _recovery_marker(db_path)
    try:
        target = _reserve_quarantine(db_path, marker)
    except FileExistsError:
        if log_error:
            log_error("[Memory] Recovery marker already exists: %s", marker)
        return None
    if not _move_quarantine_main(db_path, target, marker, log_error):
        return None
    try:
        _move_quarantine_sidecars(db_path, target)
    except OSError as move_error:
        if log_error:
            log_error("[Memory] Quarantine incomplete for %s: %s; marker %s retained, inspect %s",
                      db_path, move_error, marker, target)
        raise
    if log_error:
        log_error("[Memory] Database at %s was unreadable (%s); moved to %s; "
                  "a fresh one will be created, previous facts remain in quarantine",
                  db_path, exc, target)
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
            _import_complete_records(conn, payload)
            conn.execute(
                "INSERT INTO memory_jsonl_checkpoint(source, offset, prefix_hash) VALUES (?, ?, ?) "
                "ON CONFLICT(source) DO UPDATE SET offset=excluded.offset, prefix_hash=excluded.prefix_hash",
                (source, offset, prefix_hash),
            )
            conn.commit()
    except (OSError, sqlite3.Error, ValueError, TypeError) as exc:
        if log_error:
            log_error("[Memory] Failed to migrate facts: %s", exc)



def _import_complete_records(conn: sqlite3.Connection, payload: bytes) -> None:
    for raw_line in payload.split(b"\n"):
        try:
            _import_jsonl_line(conn, raw_line.decode("utf-8"))
        except (OverflowError, RecursionError, ValueError):
            # Bad individual data does not strand following valid records;
            # SQLite failures propagate to roll back data AND checkpoint.
            continue


def _checkpoint_matches(start: int, size: int, actual_hash: str, expected_hash: str) -> bool:
    if start < 0 or start > size:
        return False
    return start == 0 or actual_hash == expected_hash


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
        if not _checkpoint_matches(start, before.st_size, hasher.hexdigest(), expected_hash):
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
    if item.get("key", "") is None:
        return  # NOT NULL key violations must not strand following records
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
