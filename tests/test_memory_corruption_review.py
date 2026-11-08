"""Recovery must not destroy a healthy database or its WAL."""
import sqlite3

import pytest

from arena.memory import schema


def test_lock_error_never_quarantines_a_healthy_db(tmp_path, monkeypatch):
    db = tmp_path / "facts.db"
    with sqlite3.connect(db) as conn:
        conn.execute("create table sentinel (value text)")
        conn.execute("insert into sentinel values ('kept')")

    def locked(_db):
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(schema, "_prepare_memory_db", locked)
    with pytest.raises(sqlite3.OperationalError):
        schema.init_memory_db(db_path=db, jsonl_path=tmp_path / "facts.jsonl")
    assert db.exists()
    assert not list(tmp_path.glob("*.corrupt-*"))
    with sqlite3.connect(db) as conn:
        assert conn.execute("select value from sentinel").fetchone() == ("kept",)


def test_quarantine_preserves_wal_and_shm_bytes(tmp_path):
    db = tmp_path / "facts.db"
    db.write_bytes(b"broken database")
    (tmp_path / "facts.db-wal").write_bytes(b"important committed wal")
    (tmp_path / "facts.db-shm").write_bytes(b"shm contents")
    target = schema._quarantine_db(db, sqlite3.DatabaseError("corrupt"), None)
    assert target is not None
    assert target.read_bytes() == b"broken database"
    assert target.with_name(target.name + "-wal").read_bytes() == b"important committed wal"
    assert target.with_name(target.name + "-shm").read_bytes() == b"shm contents"
    assert not (tmp_path / "facts.db-wal").exists()
    assert not (tmp_path / "facts.db-shm").exists()


def test_connection_is_closed_before_quarantine_on_schema_failure(tmp_path, monkeypatch):
    db = tmp_path / "facts.db"
    db.write_bytes(b"not sqlite")
    real_connect = sqlite3.connect
    closed = []

    class TrackedConnection(sqlite3.Connection):
        def close(self):
            closed.append(True)
            return super().close()

    def tracked_connect(*args, **kwargs):
        return real_connect(*args, factory=TrackedConnection, **kwargs)

    real_quarantine = schema._quarantine_db

    def check_quarantine(*args, **kwargs):
        assert closed, "the failed connection must be closed before moving the file"
        return real_quarantine(*args, **kwargs)

    monkeypatch.setattr(schema.sqlite3, "connect", tracked_connect)
    monkeypatch.setattr(schema, "_quarantine_db", check_quarantine)
    schema.init_memory_db(db_path=db, jsonl_path=tmp_path / "facts.jsonl")
    assert closed
