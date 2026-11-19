"""Task publication must be atomic, private and preserve the previous bytes."""
from __future__ import annotations

import json
import os
from unittest import TestCase

import pytest

from arena import private_state
from arena.memory.schema import init_memory_db

CHECK = TestCase()


def test_failed_publication_preserves_old_state_and_cleans_staging(tmp_path, monkeypatch):
    target = tmp_path / "task.json"
    target.write_text('{"old": true}\n')

    def denied(*args):
        raise PermissionError("publication denied")

    original_bytes = target.read_bytes()
    with monkeypatch.context() as patch:
        patch.setattr(private_state, "_replace", denied)
        with pytest.raises(PermissionError, match="publication denied"):
            private_state.write_private_json(target, {"new": True})
    CHECK.assertEqual(target.read_bytes(), original_bytes)
    CHECK.assertEqual(list(tmp_path.glob("*.tmp")), [])
    private_state.write_private_json(target, {"new": True})
    CHECK.assertEqual(json.loads(target.read_text()), {"new": True})


def test_new_task_never_overwrites_a_colliding_id(tmp_path):
    target = tmp_path / "task.json"
    private_state.write_private_json(target, {"first": True}, replace=False)
    with pytest.raises(FileExistsError):
        private_state.write_private_json(target, {"second": True}, replace=False)
    CHECK.assertEqual(json.loads(target.read_text()), {"first": True})


@pytest.mark.skipif(os.name == "nt", reason="POSIX mode-bit enforcement")
def test_new_memory_and_tasks_are_private_under_permissive_umask(tmp_path):
    old = os.umask(0)
    try:
        task = tmp_path / "tasks" / "task.json"
        private_state.write_private_json(task, {"env": {"credential": "private"}})
        database = tmp_path / "memory" / "facts.db"
        init_memory_db(db_path=database, jsonl_path=tmp_path / "missing.jsonl")
    finally:
        os.umask(old)
    for file in (task, database):
        CHECK.assertEqual(file.stat().st_mode & 0o777, 0o600)
        CHECK.assertEqual(file.parent.stat().st_mode & 0o777, 0o700)


def test_same_corruption_error_is_reraised_when_quarantine_fails(tmp_path, monkeypatch):
    from arena.memory import schema

    original = schema.sqlite3.DatabaseError("file is not a database")

    def fail(path):
        raise original

    monkeypatch.setattr(schema, "_prepare_memory_db", fail)
    monkeypatch.setattr(schema, "_quarantine_db", lambda *args: None)
    with pytest.raises(schema.sqlite3.DatabaseError) as caught:
        schema.init_memory_db(db_path=tmp_path / "facts.db", jsonl_path=tmp_path / "facts.jsonl")
    CHECK.assertIs(caught.value, original)


def test_repeated_quarantines_do_not_depend_on_a_clock(tmp_path, monkeypatch):
    from arena.memory import schema

    # The old timestamp naming could collide while the clock stood still.
    # Freeze the clock, rather than hoping two calls happen in one tick.
    monkeypatch.setattr("time.time", lambda: 1234567890.0)
    database = tmp_path / "facts.db"
    database.write_bytes(b"first bytes")
    schema.init_memory_db(db_path=database, jsonl_path=tmp_path / "facts.jsonl")
    first = next(tmp_path.glob("facts.db.corrupt-*/facts.db"))
    CHECK.assertFalse(schema._recovery_marker(database).exists())
    database.write_bytes(b"second bytes")
    schema.init_memory_db(db_path=database, jsonl_path=tmp_path / "facts.jsonl")
    second = next(path for path in tmp_path.glob("facts.db.corrupt-*/facts.db") if path != first)
    CHECK.assertFalse(schema._recovery_marker(database).exists())
    CHECK.assertNotEqual(first, second)
    CHECK.assertEqual(first.read_bytes(), b"first bytes")
    CHECK.assertEqual(second.read_bytes(), b"second bytes")


@pytest.mark.skipif(os.name == "nt", reason="POSIX mode contract; Windows uses deployment ACLs")
def test_new_intermediate_private_directories_are_not_umask_exposed(tmp_path):
    import stat

    parent = tmp_path / "new" / "intermediate"
    target = parent / "leaf"
    previous = os.umask(0)
    try:
        private_state.private_directory(target)
    finally:
        os.umask(previous)
    for path in (tmp_path / "new", parent, target):
        CHECK.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o700)


def test_unavailable_self_parenting_root_does_not_loop():
    class UnavailableRoot:
        name = "unavailable"

        @property
        def parent(self):
            return self

        def absolute(self):
            return self

        def exists(self):
            return False

        def mkdir(self, **_kwargs):
            raise OSError("drive unavailable")

    with pytest.raises(OSError, match="drive unavailable"):
        private_state.private_directory(UnavailableRoot())


@pytest.mark.skipif(os.name == "nt", reason="POSIX directory-descriptor race contract")
def test_private_directory_never_chmods_a_substituted_symlink(tmp_path, monkeypatch):
    outside = tmp_path / "outside"
    outside.mkdir(mode=0o755)
    outside.chmod(0o755)
    target = tmp_path / "new"
    original = os.mkdir

    def substitute(path, mode=0o777, *, dir_fd=None):
        if path == "new" and dir_fd is not None:
            os.symlink(outside, path, dir_fd=dir_fd)
            return
        original(path, mode=mode, dir_fd=dir_fd)

    monkeypatch.setattr(os, "mkdir", substitute)
    with pytest.raises(OSError):
        private_state.private_directory(target)
    assert outside.stat().st_mode & 0o777 == 0o755
