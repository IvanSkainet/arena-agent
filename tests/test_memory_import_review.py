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


def test_null_key_does_not_poison_later_records_or_checkpoint(tmp_path):
    db, source = tmp_path / "facts.db", tmp_path / "facts.jsonl"
    source.write_text('{"key":null,"value":"invalid"}\n{"key":"valid","value":"kept"}\n')
    init_memory_db(db_path=db, jsonl_path=source)
    with source.open("a") as stream:
        stream.write('{"key":"later","value":"also kept"}\n')
    init_memory_db(db_path=db, jsonl_path=source)
    with sqlite3.connect(db) as conn:
        assert conn.execute("select key from memory_facts order by key").fetchall() == [("later",), ("valid",)]
        assert conn.execute("SELECT source, offset FROM memory_jsonl_checkpoint").fetchall() == [
            (str(source.resolve()), source.stat().st_size)]
