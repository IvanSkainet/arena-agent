"""Memory profile behavior tests."""
from __future__ import annotations

import asyncio
import json
import sqlite3
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from aiohttp.test_utils import make_mocked_request

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from arena.handler_context import MemoryHandlerContext  # noqa: E402
from arena.memory.handlers import make_memory_handlers  # noqa: E402
from arena.memory.runtime import MemoryRuntimeContext, make_memory_runtime  # noqa: E402
from arena.memory.schema import init_memory_db  # noqa: E402
from arena.mcp.tool_memory import handle_memory_tool  # noqa: E402
import unified_bridge as ub  # noqa: E402


def test_init_memory_db_migrates_old_schema_to_default_profile(tmp_path):
    db = tmp_path / "facts.db"
    jsonl = tmp_path / "facts.jsonl"
    with sqlite3.connect(db) as conn:
        conn.execute("CREATE TABLE memory_facts (key TEXT PRIMARY KEY, value TEXT, tags TEXT, timestamp TEXT)")
        conn.execute(
            "INSERT INTO memory_facts (key, value, tags, timestamp) VALUES (?, ?, ?, ?)",
            ("legacy", "hello", json.dumps(["old"]), "ts"),
        )
        conn.commit()
    init_memory_db(db_path=db, jsonl_path=jsonl)
    with sqlite3.connect(db) as conn:
        cols = [row[1] for row in conn.execute("PRAGMA table_info(memory_facts)").fetchall()]
        assert "profile" in cols
        row = conn.execute("SELECT profile, key, value FROM memory_facts").fetchone()
        assert row == ("default", "legacy", "hello")


class _MockCtx:
    def __init__(self, tmp_path: Path):
        self.executor = ThreadPoolExecutor(max_workers=1)
        self.runtime = make_memory_runtime(
            MemoryRuntimeContext(
                db_path=tmp_path / "facts.db",
                jsonl_path=tmp_path / "facts.jsonl",
                audit_path=tmp_path / "audit.jsonl",
                read_tail=lambda path, lines=20: [],
                utc_now=lambda: "2026-06-19T00:00:00Z",
                log_error=lambda *args, **kwargs: None,
            )
        )
        self.runtime.init_memory_db()
        self.audit_events = []

    def handler_ctx(self):
        return MemoryHandlerContext(
            require_auth=lambda request: None,
            record_request=lambda *args, **kwargs: None,
            cors_json_response=ub._cors_json_response,
            executor=self.executor,
            search_facts_paged=self.runtime.search_facts_paged,
            list_profiles=self.runtime.list_profiles,
            write_fact=self.runtime.write_fact,
            delete_fact=self.runtime.delete_fact,
            recall_sync=self.runtime.recall_sync,
            recall_digest_sync=self.runtime.recall_digest_sync,
            audit=self.audit_events.append,
            utc_now=lambda: "2026-06-19T00:00:00Z",
        )


async def _json_request(body: dict, *, path: str = "/v1/memory"):
    req = make_mocked_request("POST", path, headers={"Authorization": "Bearer t"})
    async def _json():
        return body
    req.json = _json
    return req


def test_memory_handlers_scope_get_set_delete_by_profile(tmp_path):
    env = _MockCtx(tmp_path)
    handlers = make_memory_handlers(env.handler_ctx())
    asyncio.run(handlers.memory_set(asyncio.run(_json_request({"profile": "personal", "key": "k", "value": "one"}))))
    asyncio.run(handlers.memory_set(asyncio.run(_json_request({"profile": "projects/arena", "key": "k", "value": "two"}))))

    req = make_mocked_request("GET", "/v1/memory?profile=personal", headers={"Authorization": "Bearer t"})
    resp = asyncio.run(handlers.memory_get(req))
    data = json.loads(resp.text)
    assert data["profile"] == "personal"
    assert data["count"] == 1
    assert data["facts"][0]["value"] == "one"
    assert sorted(data["profiles"]) == ["personal", "projects/arena"]

    del_req = asyncio.run(_json_request({"profile": "personal", "key": "k"}, path="/v1/memory"))
    del_resp = asyncio.run(handlers.memory_delete(del_req))
    del_data = json.loads(del_resp.text)
    assert del_data["ok"] is True
    assert del_data["profile"] == "personal"

    all_req = make_mocked_request("GET", "/v1/memory?profile=all", headers={"Authorization": "Bearer t"})
    all_resp = asyncio.run(handlers.memory_get(all_req))
    all_data = json.loads(all_resp.text)
    assert all_data["profile"] == "all"
    assert all_data["count"] == 1
    assert all_data["facts"][0]["profile"] == "projects/arena"


def test_recall_handler_scopes_by_profile(tmp_path):
    env = _MockCtx(tmp_path)
    handlers = make_memory_handlers(env.handler_ctx())
    env.runtime.write_fact({"profile": "personal", "key": "a", "value": "hello profile"})
    env.runtime.write_fact({"profile": "projects/arena", "key": "b", "value": "hello project"})
    req = make_mocked_request("GET", "/v1/recall?q=hello&profile=projects/arena", headers={"Authorization": "Bearer t"})
    resp = asyncio.run(handlers.recall(req))
    data = json.loads(resp.text)
    assert data["profile"] == "projects/arena"
    assert data["facts"][0]["fact"]["profile"] == "projects/arena"


class _McpCtx:
    def __init__(self):
        self.facts = []
        self.audit_events = []

    def write_fact(self, entry):
        self.facts.append(entry)

    def load_facts(self, profile="default"):
        if profile is None:
            return list(self.facts)
        return [f for f in self.facts if f.get("profile", "default") == profile]

    def recall_sync(self, query, top, profile="default"):
        facts = self.load_facts(profile)
        return {"ok": True, "query": query, "count": len(facts), "facts": [{"fact": f, "score": 1.0} for f in facts[:top]]}

    def recall_digest_sync(self, profile="default"):
        return {"ok": True, "profile": profile, "digest": "# Memory Digest\n\nbody"}

    def audit(self, event):
        self.audit_events.append(event)



def test_mcp_memory_tools_accept_profile():
    ctx = _McpCtx()
    result = handle_memory_tool("mem.set", {"profile": "projects/arena", "key": "x", "value": "y"}, ctx=ctx, run_local=None)
    assert result is not None
    assert ctx.facts[0]["profile"] == "projects/arena"
    get_result = handle_memory_tool("mem.get", {"query": "", "profile": "projects/arena"}, ctx=ctx, run_local=None)
    payload = json.loads(get_result["content"][0]["text"])
    assert payload["profile"] == "projects/arena"
    assert payload["facts"][0]["profile"] == "projects/arena"
