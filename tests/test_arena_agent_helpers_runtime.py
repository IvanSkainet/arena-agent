"""Unit tests for arena.agent_helpers.runtime (v4.79.0 coverage lift).

Covers ``load_facts`` and ``put_fact`` -- the JSONL-backed
``memory/facts.jsonl`` reader/writer. These functions are
touched by the agent-side chat scripts but were never
imported by the test suite.
"""
from __future__ import annotations

import json
import os
import stat
import tempfile
from pathlib import Path


_tmp_home = Path(tempfile.mkdtemp(prefix="arena_helpers_runtime_"))
os.environ["ARENA_AGENT_HOME"] = str(_tmp_home)

from arena.agent_helpers import runtime  # noqa: E402


def test_load_facts_returns_empty_when_no_file(monkeypatch, tmp_path):
    # Point FACTS at a path that doesn't exist yet.
    monkeypatch.setattr(runtime, "FACTS", tmp_path / "missing.jsonl")
    assert runtime.load_facts() == []


def test_put_fact_appends_jsonl_record(monkeypatch, tmp_path):
    target = tmp_path / "facts.jsonl"
    monkeypatch.setattr(runtime, "FACTS", target)
    runtime.put_fact("k", "v", tags=["t1", "t2"])
    assert target.exists()
    rec = json.loads(target.read_text(encoding="utf-8").strip())
    assert rec["key"] == "k"
    assert rec["value"] == "v"
    assert rec["tags"] == ["t1", "t2"]
    assert rec["type"] == "fact"
    assert rec["ts"].endswith("+00:00")


def test_put_fact_sets_owner_only_mode(monkeypatch, tmp_path):
    target = tmp_path / "facts.jsonl"
    monkeypatch.setattr(runtime, "FACTS", target)
    runtime.put_fact("k", "v")
    if hasattr(os, "geteuid"):  # POSIX
        mode = stat.S_IMODE(target.stat().st_mode)
        assert mode == 0o600


def test_load_facts_filters_by_query(monkeypatch, tmp_path):
    target = tmp_path / "facts.jsonl"
    monkeypatch.setattr(runtime, "FACTS", target)
    runtime.put_fact("bridge", "v4.79.0", tags=["release"])
    runtime.put_fact("lunch", "sushi", tags=["personal"])
    runtime.put_fact("bridge2", "v4.80.0", tags=["release"])
    out = runtime.load_facts("bridge")
    assert len(out) == 2
    assert {o["key"] for o in out} == {"bridge", "bridge2"}


def test_load_facts_respects_limit(monkeypatch, tmp_path):
    target = tmp_path / "facts.jsonl"
    monkeypatch.setattr(runtime, "FACTS", target)
    for i in range(10):
        runtime.put_fact(f"k{i}", f"v{i}")
    out = runtime.load_facts(limit=3)
    assert len(out) == 3
    # Last 3 records are returned (most recent).
    assert [o["key"] for o in out] == ["k7", "k8", "k9"]


def test_load_facts_skips_malformed_lines(monkeypatch, tmp_path):
    target = tmp_path / "facts.jsonl"
    monkeypatch.setattr(runtime, "FACTS", target)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        'not json\n'
        '{"key": "ok", "value": "v", "tags": []}\n',
        encoding="utf-8",
    )
    out = runtime.load_facts()
    assert len(out) == 1
    assert out[0]["key"] == "ok"
