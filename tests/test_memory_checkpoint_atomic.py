"""Transactional JSONL import: no stale replay, even across processes."""
from __future__ import annotations

import json
import sqlite3
import subprocess
import sys

import pytest

from arena.memory.schema import init_memory_db, migrate_jsonl_facts


def _fact(key, value):
    return json.dumps({"key": key, "value": value}) + "\n"


def _value(db, key):
    with sqlite3.connect(db) as conn:
        row = conn.execute("SELECT value FROM memory_facts WHERE key=?", (key,)).fetchone()
    return None if row is None else row[0]


@pytest.mark.parametrize("extra", [0, 100])
def test_replacement_same_size_or_larger_is_imported(tmp_path, extra):
    db, source = tmp_path / "facts.db", tmp_path / "facts.jsonl"
    source.write_text(_fact("old", "aaaa"), encoding="utf-8")
    init_memory_db(db_path=db, jsonl_path=source)
    old_size = source.stat().st_size
    replacement = _fact("new", "b" * (4 + extra))
    assert len(replacement.encode()) >= old_size
    source.write_text(replacement, encoding="utf-8")  # truncate/rewrite in place
    migrate_jsonl_facts(db_path=db, jsonl_path=source)
    assert _value(db, "new") == "b" * (4 + extra)


def test_rotation_with_initially_incomplete_record_keeps_reset(tmp_path):
    db, source = tmp_path / "facts.db", tmp_path / "facts.jsonl"
    source.write_text(_fact("old", "x" * 200), encoding="utf-8")
    init_memory_db(db_path=db, jsonl_path=source)
    record = _fact("new", "y" * 300)
    source.write_text(record[:15], encoding="utf-8")
    migrate_jsonl_facts(db_path=db, jsonl_path=source)
    with source.open("a", encoding="utf-8") as handle:
        handle.write(record[15:])
    migrate_jsonl_facts(db_path=db, jsonl_path=source)
    assert _value(db, "new") == "y" * 300


def test_import_and_checkpoint_rollback_together(tmp_path):
    db, source = tmp_path / "facts.db", tmp_path / "facts.jsonl"
    init_memory_db(db_path=db, jsonl_path=source)
    source.write_text(_fact("a", "first") + _fact("b", "second"), encoding="utf-8")
    with sqlite3.connect(db) as conn:
        conn.execute("CREATE TRIGGER reject_b BEFORE INSERT ON memory_facts "
                     "WHEN NEW.key='b' BEGIN SELECT RAISE(ABORT, 'blocked'); END")
    errors = []
    migrate_jsonl_facts(db_path=db, jsonl_path=source,
                        log_error=lambda fmt, *args: errors.append(fmt % args))
    assert errors
    assert _value(db, "a") is None
    with sqlite3.connect(db) as conn:
        conn.execute("DROP TRIGGER reject_b")
    migrate_jsonl_facts(db_path=db, jsonl_path=source)
    assert _value(db, "a") == "first"
    assert _value(db, "b") == "second"


def test_parallel_processes_serialize_and_do_not_replay(tmp_path):
    db, source = tmp_path / "facts.db", tmp_path / "facts.jsonl"
    init_memory_db(db_path=db, jsonl_path=source)
    source.write_text("".join(_fact(f"k{i}", f"v{i}") for i in range(50)), encoding="utf-8")
    code = ("import sys; from pathlib import Path; from arena.memory.schema import migrate_jsonl_facts; "
            "migrate_jsonl_facts(db_path=Path(sys.argv[1]), jsonl_path=Path(sys.argv[2]), "
            "log_error=lambda f,*a: (_ for _ in ()).throw(RuntimeError(f % a)))")
    processes = [subprocess.Popen([sys.executable, "-c", code, str(db), str(source)],
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                 for _ in range(4)]
    for process in processes:
        stdout, stderr = process.communicate(timeout=60)
        assert process.returncode == 0, (stdout, stderr)
    with sqlite3.connect(db) as conn:
        assert conn.execute("SELECT count(*) FROM memory_facts").fetchone()[0] == 50
        conn.execute("UPDATE memory_facts SET value='api edit' WHERE key='k0'")
    migrate_jsonl_facts(db_path=db, jsonl_path=source)
    assert _value(db, "k0") == "api edit"


def test_non_scalar_fields_do_not_block_following_record(tmp_path):
    db, source = tmp_path / "facts.db", tmp_path / "facts.jsonl"
    source.write_text('{"key":"bad","value":[]}\n' + _fact("good", "yes"), encoding="utf-8")
    init_memory_db(db_path=db, jsonl_path=source)
    assert _value(db, "good") == "yes"
    assert _value(db, "bad") is None
