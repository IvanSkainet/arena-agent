"""Memory runtime wrapper extraction tests."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import unified_bridge as ub  # noqa: E402
from arena.memory.runtime import MemoryRuntimeContext, make_memory_runtime  # noqa: E402


def _runtime(tmp_path: Path):
    return make_memory_runtime(MemoryRuntimeContext(
        db_path=tmp_path / "facts.db",
        jsonl_path=tmp_path / "facts.jsonl",
        audit_path=tmp_path / "audit.jsonl",
        read_tail=lambda path, lines=100: ["audit line"],
        utc_now=lambda: "now",
        log_error=lambda *args, **kwargs: None,
    ))


def test_memory_runtime_factory_outputs(tmp_path):
    runtime = _runtime(tmp_path)
    assert callable(runtime.init_memory_db)
    assert callable(runtime.load_facts)
    assert callable(runtime.list_profiles)
    assert callable(runtime.search_facts_paged)
    assert callable(runtime.write_fact)
    assert callable(runtime.delete_fact)
    assert callable(runtime.recall_sync)
    assert callable(runtime.recall_digest_sync)


def test_unified_memory_runtime_bindings():
    assert ub.init_memory_db.__module__ == "arena.memory.runtime"
    assert ub._load_facts.__module__ == "arena.memory.runtime"
    assert ub._list_memory_profiles.__module__ == "arena.memory.runtime"
    assert ub._search_facts_paged.__module__ == "arena.memory.runtime"
    assert ub._write_fact.__module__ == "arena.memory.runtime"
    assert ub._delete_fact.__module__ == "arena.memory.runtime"
    assert ub._recall_sync.__module__ == "arena.memory.runtime"
    assert ub._recall_digest_sync.__module__ == "arena.memory.runtime"


def test_memory_runtime_crud_recall_digest(tmp_path):
    runtime = _runtime(tmp_path)
    runtime.init_memory_db()
    runtime.write_fact({"profile": "personal", "key": "k1", "value": "hello world", "tags": ["unit"]})
    runtime.write_fact({"profile": "projects/arena", "key": "k1", "value": "project note", "tags": ["code"]})
    facts = runtime.load_facts("personal")
    assert len(facts) == 1
    assert runtime.list_profiles() == ["personal", "projects/arena"]
    total, rows = runtime.search_facts_paged("hello", profile="personal")
    assert total == 1
    assert rows[0]["key"] == "k1"
    total_all, _ = runtime.search_facts_paged("", profile=None)
    assert total_all == 2
    recall = runtime.recall_sync("hello", 5, "personal")
    assert recall["ok"] is True
    digest = runtime.recall_digest_sync("personal")
    assert digest["ok"] is True
    assert digest["profile"] == "personal"
    assert runtime.delete_fact("k1", "personal") is True
