"""Tests for memory.export and memory.import MCP tools."""
import sys
import json
import sqlite3
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from arena.mcp.tool_memory_export_import import handle_memory_export_import_tool  # noqa: E402
from arena.mcp.tool_registry import MCP_TOOLS  # noqa: E402


class _MockCtx:
    """Mock ctx that provides a memory db path."""
    def __init__(self, db_path):
        self._db_path = Path(db_path)

    @property
    def memory_db_path(self):
        return self._db_path

    def app_config(self):
        return {}


def _make_db(db_path: Path, facts: list[dict] = None):
    """Create a test memory database with optional initial facts."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as conn:
        conn.execute('''CREATE TABLE IF NOT EXISTS memory_facts (
            profile TEXT NOT NULL, key TEXT NOT NULL, value TEXT, tags TEXT, timestamp TEXT,
            PRIMARY KEY (profile, key))''')
        for f in (facts or []):
            conn.execute('INSERT INTO memory_facts (profile, key, value, tags, timestamp) VALUES (?, ?, ?, ?, ?)',
                         (f.get("profile", "default"), f["key"], f["value"], json.dumps(f.get("tags", [])), f.get("timestamp", "")))
        conn.commit()


# ============================================================
# memory.export tests
# ============================================================

def test_export_empty_db(tmp_path):
    """memory.export on empty database returns empty."""
    db = tmp_path / "facts.db"
    _make_db(db)
    ctx = _MockCtx(db)
    result = handle_memory_export_import_tool("memory.export", {}, ctx=ctx)
    assert result is not None
    assert not result.get("isError")
    text = result["content"][0]["text"]
    assert text == "[]"


def test_export_with_facts(tmp_path):
    """memory.export returns all facts as JSONL."""
    db = tmp_path / "facts.db"
    _make_db(db, [
        {"profile": "default", "key": "k1", "value": "v1", "tags": ["t1"], "timestamp": "2026-01-01T00:00:00Z"},
        {"profile": "projects/arena", "key": "k2", "value": "v2", "tags": [], "timestamp": "2026-01-02T00:00:00Z"},
    ])
    ctx = _MockCtx(db)
    result = handle_memory_export_import_tool("memory.export", {}, ctx=ctx)
    assert result is not None
    assert not result.get("isError")
    text = result["content"][0]["text"]
    lines = text.strip().split("\n")
    assert len(lines) == 2
    f1 = json.loads(lines[0])
    assert f1["profile"] == "default"
    assert f1["key"] == "k1"
    assert f1["value"] == "v1"
    assert f1["tags"] == ["t1"]
    f2 = json.loads(lines[1])
    assert f2["profile"] == "projects/arena"
    assert f2["key"] == "k2"


def test_export_nonexistent_db(tmp_path):
    """memory.export on non-existent db returns empty."""
    db = tmp_path / "nonexistent.db"
    ctx = _MockCtx(db)
    result = handle_memory_export_import_tool("memory.export", {}, ctx=ctx)
    assert result is not None
    assert not result.get("isError")
    assert result["content"][0]["text"] == "[]"


def test_export_profile_filter(tmp_path):
    db = tmp_path / "facts.db"
    _make_db(db, [
        {"profile": "personal", "key": "a", "value": "1", "tags": []},
        {"profile": "projects/arena", "key": "b", "value": "2", "tags": []},
    ])
    ctx = _MockCtx(db)
    result = handle_memory_export_import_tool("memory.export", {"profile": "projects/arena"}, ctx=ctx)
    text = result["content"][0]["text"]
    lines = text.strip().split("\n")
    assert len(lines) == 1
    assert json.loads(lines[0])["profile"] == "projects/arena"


# ============================================================
# memory.import tests
# ============================================================

def test_import_basic(tmp_path):
    """memory.import adds facts from JSONL."""
    db = tmp_path / "facts.db"
    _make_db(db)
    ctx = _MockCtx(db)
    data = json.dumps({"key": "imported1", "value": "hello", "tags": ["new"]}) + "\n" + json.dumps({"profile": "projects/arena", "key": "imported2", "value": "world", "tags": []})
    result = handle_memory_export_import_tool("memory.import", {"data": data}, ctx=ctx)
    assert result is not None
    assert not result.get("isError")
    assert "2 fact(s)" in result["content"][0]["text"]
    with sqlite3.connect(db) as conn:
        rows = conn.execute("SELECT profile, key, value FROM memory_facts ORDER BY profile, key").fetchall()
        assert len(rows) == 2
        assert rows[0] == ("default", "imported1", "hello")
        assert rows[1] == ("projects/arena", "imported2", "world")


def test_import_overwrite_mode(tmp_path):
    """memory.import with overwrite=true replaces targeted profile facts."""
    db = tmp_path / "facts.db"
    _make_db(db, [
        {"profile": "default", "key": "old1", "value": "old_val", "tags": [], "timestamp": ""},
        {"profile": "projects/arena", "key": "keep", "value": "keep_val", "tags": [], "timestamp": ""},
    ])
    ctx = _MockCtx(db)
    data = json.dumps({"key": "new1", "value": "new_val", "tags": []})
    result = handle_memory_export_import_tool("memory.import", {"data": data, "overwrite": True, "profile": "default"}, ctx=ctx)
    assert result is not None
    assert not result.get("isError")
    assert "overwrite" in result["content"][0]["text"]
    with sqlite3.connect(db) as conn:
        rows = conn.execute("SELECT profile, key FROM memory_facts ORDER BY profile, key").fetchall()
        assert rows == [("default", "new1"), ("projects/arena", "keep")]


def test_import_missing_data(tmp_path):
    """memory.import errors when data is missing."""
    db = tmp_path / "facts.db"
    _make_db(db)
    ctx = _MockCtx(db)
    result = handle_memory_export_import_tool("memory.import", {}, ctx=ctx)
    assert result is not None
    assert result.get("isError") is True
    assert "missing" in result["content"][0]["text"].lower()


def test_import_invalid_json(tmp_path):
    """memory.import skips invalid JSON lines and reports errors."""
    db = tmp_path / "facts.db"
    _make_db(db)
    ctx = _MockCtx(db)
    data = '{"key": "valid", "value": "ok"}\nnot json\n{"missing_key": "no key"}'
    result = handle_memory_export_import_tool("memory.import", {"data": data}, ctx=ctx)
    assert result is not None
    assert not result.get("isError")
    text = result["content"][0]["text"]
    assert "1 fact(s)" in text
    assert "error" in text.lower()


def test_import_upsert_existing(tmp_path):
    """memory.import updates existing keys (upsert) within the same profile."""
    db = tmp_path / "facts.db"
    _make_db(db, [{"profile": "default", "key": "k1", "value": "old", "tags": [], "timestamp": "old_ts"}])
    ctx = _MockCtx(db)
    data = json.dumps({"key": "k1", "value": "new", "tags": ["updated"], "timestamp": "new_ts"})
    result = handle_memory_export_import_tool("memory.import", {"data": data}, ctx=ctx)
    assert result is not None
    with sqlite3.connect(db) as conn:
        rows = conn.execute("SELECT value, tags FROM memory_facts WHERE profile='default' AND key='k1'").fetchone()
        assert rows[0] == "new"
        assert json.loads(rows[1]) == ["updated"]


def test_import_empty_data(tmp_path):
    """memory.import errors on empty data."""
    db = tmp_path / "facts.db"
    _make_db(db)
    ctx = _MockCtx(db)
    result = handle_memory_export_import_tool("memory.import", {"data": ""}, ctx=ctx)
    assert result is not None
    assert result.get("isError") is True


# ============================================================
# Registry tests
# ============================================================

def test_memory_export_in_registry():
    names = [t["name"] for t in MCP_TOOLS]
    assert "memory.export" in names


def test_memory_import_in_registry():
    names = [t["name"] for t in MCP_TOOLS]
    assert "memory.import" in names


def test_memory_import_schema():
    tool = next(t for t in MCP_TOOLS if t["name"] == "memory.import")
    assert "data" in tool["inputSchema"]["required"]
    assert "overwrite" in tool["inputSchema"]["properties"]


# ============================================================
# Round-trip test
# ============================================================

def test_export_then_import_roundtrip(tmp_path):
    """Export from one db, import into another — data matches."""
    src_db = tmp_path / "src.db"
    _make_db(src_db, [
        {"profile": "default", "key": "a", "value": "1", "tags": ["x"], "timestamp": "2026-01-01"},
        {"profile": "projects/arena", "key": "b", "value": "2", "tags": ["y"], "timestamp": "2026-01-02"},
    ])
    dst_db = tmp_path / "dst.db"
    _make_db(dst_db)
    ctx_src = _MockCtx(src_db)
    export_result = handle_memory_export_import_tool("memory.export", {}, ctx=ctx_src)
    assert not export_result.get("isError")
    exported_data = export_result["content"][0]["text"]
    ctx_dst = _MockCtx(dst_db)
    import_result = handle_memory_export_import_tool("memory.import", {"data": exported_data}, ctx=ctx_dst)
    assert not import_result.get("isError")
    assert "2 fact(s)" in import_result["content"][0]["text"]
    with sqlite3.connect(dst_db) as conn:
        rows = conn.execute("SELECT profile, key, value FROM memory_facts ORDER BY profile, key").fetchall()
        assert rows == [("default", "a", "1"), ("projects/arena", "b", "2")]
