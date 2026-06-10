"""Memory store helper tests."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from arena.memory.store import delete_fact, init_memory_db, load_facts, recall, recall_digest, search_facts_paged, write_fact  # noqa: E402
import unified_bridge as ub  # noqa: E402


def test_memory_store_roundtrip(tmp_path):
    db = tmp_path / "memory" / "facts.db"
    jsonl = tmp_path / "memory" / "facts.jsonl"
    init_memory_db(db_path=db, jsonl_path=jsonl)
    write_fact(db, {"key": "k1", "value": "hello world", "tags": ["t"], "timestamp": "2026"})
    facts = load_facts(db)
    assert len(facts) == 1
    assert facts[0]["tags"] == ["t"]
    total, page = search_facts_paged(db, q="hello", offset=0, limit=10)
    assert total == 1
    assert page[0]["key"] == "k1"
    assert delete_fact(db, "k1") is True
    assert load_facts(db) == []


def test_recall_and_digest():
    facts = [{"key": "alpha", "value": "red apple", "tags": [], "timestamp": "t"}]
    res = recall("apple", facts=facts, top=5)
    assert res["ok"] is True
    assert res["facts"][0]["fact"]["key"] == "alpha"
    digest = recall_digest(facts=facts, audit_lines=['{"type":"x","ts":"now"}'], utc_now_fn=lambda: "now")
    assert digest["ok"] is True
    assert "Memory Digest" in digest["digest"]


def test_unified_memory_wrappers():
    assert callable(ub._load_facts)
    assert callable(ub._recall_sync)
