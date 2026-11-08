"""Recovery must not destroy a healthy database or its WAL."""
import sqlite3
from contextlib import closing

import pytest

from arena.memory import schema


def test_lock_error_never_quarantines_a_healthy_db(tmp_path, monkeypatch):
    db = tmp_path / "facts.db"
    with closing(sqlite3.connect(db)) as conn, conn:
        conn.execute("create table sentinel (value text)")
        conn.execute("insert into sentinel values ('kept')")

    def locked(_db):
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(schema, "_prepare_memory_db", locked)
    with pytest.raises(sqlite3.OperationalError):
        schema.init_memory_db(db_path=db, jsonl_path=tmp_path / "facts.jsonl")
    assert db.exists()
    assert not list(tmp_path.glob("*.corrupt-*"))
    with closing(sqlite3.connect(db)) as conn, conn:
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


def test_legacy_sqlite_errors_are_identified_narrowly():
    # Python 3.10 exceptions do not expose sqlite_errorcode.
    assert schema._is_corruption_error(sqlite3.DatabaseError("database disk image is malformed"))
    assert schema._is_corruption_error(sqlite3.DatabaseError("file is not a database"))
    assert not schema._is_corruption_error(sqlite3.DatabaseError("database is locked"))
    assert not schema._is_corruption_error(sqlite3.DatabaseError("not a database, maybe"))
    assert not schema._is_corruption_error(sqlite3.OperationalError("database disk image is malformed"))
    with_code = sqlite3.DatabaseError("database disk image is malformed")
    with_code.sqlite_errorcode = 5  # SQLITE_BUSY
    assert not schema._is_corruption_error(with_code)
    with_code.sqlite_errorcode = 11 | (2 << 8)  # extended SQLITE_CORRUPT
    assert schema._is_corruption_error(with_code)


def test_legacy_corruption_error_can_recover_but_other_errors_cannot(tmp_path, monkeypatch):
    db = tmp_path / "facts.db"
    db.write_bytes(b"not sqlite")
    real_prepare = schema._prepare_memory_db
    calls = 0

    def legacy_prepare(path):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise sqlite3.DatabaseError("file is not a database")
        return real_prepare(path)

    monkeypatch.setattr(schema, "_prepare_memory_db", legacy_prepare)
    schema.init_memory_db(db_path=db, jsonl_path=tmp_path / "facts.jsonl")
    assert calls == 2
    assert (list(tmp_path.glob("facts.db.corrupt-*"))[0] / db.name).read_bytes() == b"not sqlite"


def test_sidecar_move_failure_blocks_restart_and_preserves_bytes(tmp_path, monkeypatch):
    db = tmp_path / "facts.db"
    wal = tmp_path / "facts.db-wal"
    db.write_bytes(b"broken db bytes")
    wal.write_bytes(b"important wal bytes")
    real_replace = schema.os.replace

    def fail_wal(src, dst):
        if src == wal:
            raise PermissionError("sidecar busy")
        return real_replace(src, dst)

    with monkeypatch.context() as patch:
        patch.setattr(schema.os, "replace", fail_wal)
        with pytest.raises(PermissionError, match="sidecar busy"):
            schema._quarantine_db(db, sqlite3.DatabaseError("corrupt"), None)
    marker = schema._recovery_marker(db)
    assert marker.exists()
    with pytest.raises(RuntimeError, match="recovery is incomplete"):
        schema.init_memory_db(db_path=db, jsonl_path=tmp_path / "facts.jsonl")
    assert wal.read_bytes() == b"important wal bytes"
    assert not db.exists()
    assert (list(tmp_path.glob("facts.db.corrupt-*"))[0] / db.name).read_bytes() == b"broken db bytes"


def test_failed_database_move_removes_marker_without_losing_source(tmp_path, monkeypatch):
    db = tmp_path / "facts.db"
    db.write_bytes(b"broken")

    def fail_move(src, dst):
        raise PermissionError("locked")

    monkeypatch.setattr(schema.os, "replace", fail_move)
    assert schema._quarantine_db(db, sqlite3.DatabaseError("corrupt"), None) is None
    assert db.read_bytes() == b"broken"
    assert not schema._recovery_marker(db).exists()


@pytest.mark.skipif(__import__('os').name == 'nt', reason='POSIX mode bits do not model Windows ACLs')
def test_replacement_and_quarantine_directory_are_private_with_open_umask(tmp_path):
    import os
    import stat

    db = tmp_path / "facts.db"
    db.write_bytes(b"not sqlite")
    db.chmod(0o644)
    old_umask = os.umask(0)
    try:
        schema.init_memory_db(db_path=db, jsonl_path=tmp_path / "facts.jsonl")
    finally:
        os.umask(old_umask)
    directory = list(tmp_path.glob("facts.db.corrupt-*"))[0]
    assert stat.S_IMODE(directory.stat().st_mode) == 0o700
    assert stat.S_IMODE(db.stat().st_mode) == 0o600
    assert (directory / db.name).read_bytes() == b"not sqlite"


def test_quarantine_collision_never_overwrites_prior_files(tmp_path, monkeypatch):
    db = tmp_path / "facts.db"
    db.write_bytes(b"new damaged database")
    prior = tmp_path / "facts.db.corrupt-collision"
    prior.mkdir()
    (prior / db.name).write_bytes(b"first saved database")
    monkeypatch.setattr(schema.tempfile, "_get_candidate_names", lambda: iter(["collision", "fresh"]))

    target = schema._quarantine_db(db, sqlite3.DatabaseError("corrupt"), None)

    assert target == tmp_path / "facts.db.corrupt-fresh" / db.name
    assert target.read_bytes() == b"new damaged database"
    assert (prior / db.name).read_bytes() == b"first saved database"
