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

    with monkeypatch.context() as patch:
        patch.setattr(private_state, "_replace", denied)
        with pytest.raises(PermissionError, match="publication denied"):
            private_state.write_private_json(target, {"new": True})
    CHECK.assertEqual(json.loads(target.read_text()), {"old": True})
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
