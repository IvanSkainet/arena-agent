"""Malformed records and Unicode line separators must not hide later facts."""
import json
import sqlite3

from arena.memory.schema import init_memory_db


def test_non_object_json_does_not_block_later_facts(tmp_path):
    db = tmp_path / "facts.db"
    jsonl = tmp_path / "facts.jsonl"
    jsonl.write_text('null\n[]\n42\n"str"\n{"key":"valid","value":"seen"}\n', encoding="utf-8")
    init_memory_db(db_path=db, jsonl_path=jsonl)
    with sqlite3.connect(db) as conn:
        assert conn.execute("select value from memory_facts where key='valid'").fetchone() == ("seen",)


def test_unicode_line_separator_in_value_is_not_a_record_boundary(tmp_path):
    db = tmp_path / "facts.db"
    jsonl = tmp_path / "facts.jsonl"
    jsonl.write_text(json.dumps({"key": "k", "value": "before\u2028after", "ts": "date"},
                                ensure_ascii=False) + "\n", encoding="utf-8")
    init_memory_db(db_path=db, jsonl_path=jsonl)
    with sqlite3.connect(db) as conn:
        assert conn.execute("select value, timestamp from memory_facts where key='k'").fetchone() == (
            "before\u2028after", "date")
