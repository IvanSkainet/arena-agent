"""A corrupt facts database must not take the bridge down with it.

`init_memory_db` runs while the application is assembled. Before this change a
truncated `memory/facts.db` raised `sqlite3.DatabaseError` straight out of
`serve`: no `/health`, no `/v1/fs`, no dashboard, and a traceback that named
neither the file nor a remedy. The same corruption of any *other* state file
(`mission.json`, `queue/done/*.json`, `PLAN.md`) was already survivable, so one
binary file could switch off 536 routes that the rest of the state layer
degrades around.

Reproduced on a live bridge (2026-11-07 durability round): the file was cut in
half, `serve` exited rc=1 with `database disk image is malformed`, and deleting
the file by hand was the only recovery -- undiscoverable from the log.
"""
from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path

from arena.memory import schema
from arena.memory.schema import init_memory_db


def _seed(db: Path) -> None:
    with closing(sqlite3.connect(db)) as conn, conn:
        conn.execute("CREATE TABLE marker (x TEXT)")
        conn.commit()


def _truncate(db: Path) -> bytes:
    """Cut the file in half, the way a power loss or a full disk does."""
    raw = db.read_bytes()
    broken = raw[: max(1, len(raw) // 2)]
    db.write_bytes(broken)
    return broken


def _assert_unreadable(db: Path) -> None:
    try:
        with closing(sqlite3.connect(db)) as conn, conn:
            conn.execute("SELECT 1 FROM sqlite_master").fetchall()
    except sqlite3.DatabaseError:
        return
    raise AssertionError("the fixture did not actually corrupt the database")


def test_a_corrupt_database_does_not_raise_out_of_startup(tmp_path):
    """The whole finding: this call used to raise and take `serve` with it."""
    db = tmp_path / "memory" / "facts.db"
    db.parent.mkdir(parents=True)
    _seed(db)
    _truncate(db)
    _assert_unreadable(db)

    # Authored as "must not raise" rather than "must not raise DatabaseError":
    # a fix that swapped the exception for a different one would still brick
    # startup, which is the thing being prevented.
    messages: list[str] = []
    try:
        init_memory_db(
            db_path=db,
            jsonl_path=tmp_path / "memory" / "facts.jsonl",
            log_error=lambda fmt, *args: messages.append(fmt % args if args else fmt),
        )
    except sqlite3.DatabaseError as exc:
        raise AssertionError(
            f"SQLite {sqlite3.sqlite_version}, code={getattr(exc, 'sqlite_errorcode', None)}, "
            f"name={getattr(exc, 'sqlite_errorname', None)}, recovery log={messages!r}"
        ) from exc

    with closing(sqlite3.connect(db)) as conn, conn:
        tables = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()}
    assert "memory_facts" in tables, "the replacement database was not initialised"


def test_the_corrupt_file_is_moved_aside_not_deleted(tmp_path):
    """The bytes may be the only copy of the operator's facts."""
    db = tmp_path / "memory" / "facts.db"
    db.parent.mkdir(parents=True)
    _seed(db)
    broken = _truncate(db)

    init_memory_db(db_path=db, jsonl_path=tmp_path / "memory" / "facts.jsonl")

    quarantined = sorted(db.parent.glob("facts.db.corrupt-*"))
    assert len(quarantined) == 1, f"expected one quarantine file, got {quarantined}"
    assert quarantined[0].read_bytes() == broken, "the quarantined file is not the broken one"


def test_the_operator_is_told_what_happened_and_where(tmp_path):
    """A brick that heals silently is still a brick nobody can explain."""
    db = tmp_path / "memory" / "facts.db"
    db.parent.mkdir(parents=True)
    _seed(db)
    _truncate(db)
    messages: list[str] = []

    init_memory_db(
        db_path=db,
        jsonl_path=tmp_path / "memory" / "facts.jsonl",
        log_error=lambda fmt, *args: messages.append(fmt % args if args else fmt),
    )

    blob = "\n".join(messages)
    assert str(db) in blob, "the log line does not name the file"
    assert "corrupt" in blob.lower() or "unreadable" in blob.lower()
    quarantined = sorted(db.parent.glob("facts.db.corrupt-*"))
    assert quarantined and str(quarantined[0]) in blob, "the log line does not name the new path"


def test_a_healthy_database_is_left_completely_alone(tmp_path):
    """The recovery path must not fire on a file that was never broken.

    Asserted on what the file *means*, not on its bytes: SQLite rewrites the
    header change counter on every open, so byte-equality would fail on a
    perfectly healthy database and teach the wrong lesson.
    """
    db = tmp_path / "memory" / "facts.db"
    db.parent.mkdir(parents=True)
    init_memory_db(db_path=db, jsonl_path=tmp_path / "memory" / "facts.jsonl")
    with closing(sqlite3.connect(db)) as conn, conn:
        conn.execute(
            "INSERT OR REPLACE INTO memory_facts (profile, key, value, tags, timestamp)"
            " VALUES ('default', 'survivor', 'still here', '[]', '2026-11-07T00:00:00+00:00')"
        )
        conn.commit()

    init_memory_db(db_path=db, jsonl_path=tmp_path / "memory" / "facts.jsonl")

    assert not list(db.parent.glob("facts.db.corrupt-*")), "healthy file was quarantined"
    with closing(sqlite3.connect(db)) as conn, conn:
        row = conn.execute("SELECT value FROM memory_facts WHERE key='survivor'").fetchone()
    assert row == ("still here",), "a healthy restart lost a fact"


def test_facts_survive_when_only_the_sidecars_are_stale(tmp_path):
    """A WAL left behind by a killed process is not corruption."""
    db = tmp_path / "memory" / "facts.db"
    db.parent.mkdir(parents=True)
    init_memory_db(db_path=db, jsonl_path=tmp_path / "memory" / "facts.jsonl")
    with closing(sqlite3.connect(db)) as conn, conn:
        conn.execute(
            "INSERT OR REPLACE INTO memory_facts (profile, key, value, tags, timestamp)"
            " VALUES ('default', 'kept', 'yes', '[]', '2026-11-07T00:00:00+00:00')"
        )
        conn.commit()

    (db.parent / "facts.db-wal").write_bytes(b"\x00" * 32)  # leftover, not a valid WAL

    init_memory_db(db_path=db, jsonl_path=tmp_path / "memory" / "facts.jsonl")

    with closing(sqlite3.connect(db)) as conn, conn:
        row = conn.execute("SELECT value FROM memory_facts WHERE key='kept'").fetchone()
    assert row is not None and row[0] == "yes", "a stale sidecar cost us a fact"


def test_the_quarantine_name_never_overwrites_an_earlier_one(tmp_path):
    """Two crashes in a row must leave two files: the first is the interesting one."""
    db = tmp_path / "memory" / "facts.db"
    db.parent.mkdir(parents=True)
    _seed(db)
    _truncate(db)
    init_memory_db(db_path=db, jsonl_path=tmp_path / "memory" / "facts.jsonl")
    first = sorted(db.parent.glob("facts.db.corrupt-*"))

    _truncate(db)  # corrupt the replacement too
    init_memory_db(db_path=db, jsonl_path=tmp_path / "memory" / "facts.jsonl")
    second = sorted(db.parent.glob("facts.db.corrupt-*"))

    assert len(second) == 2, f"the second quarantine overwrote the first: {second}"
    assert first[0] in second


def test_an_unmovable_database_still_raises(tmp_path, monkeypatch):
    """When nothing can be done, fail loudly instead of pretending to start."""
    db = tmp_path / "memory" / "facts.db"
    db.parent.mkdir(parents=True)
    _seed(db)
    _truncate(db)

    def _deny(src, dst):
        raise OSError("read-only file system")

    monkeypatch.setattr(schema.os, "replace", _deny)

    try:
        init_memory_db(db_path=db, jsonl_path=tmp_path / "memory" / "facts.jsonl")
    except sqlite3.DatabaseError:
        return
    raise AssertionError("an unrepairable database started anyway")
