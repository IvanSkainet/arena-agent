"""Unit tests for arena.agent_helpers.runtime (v4.79.0 coverage lift).

Covers ``load_facts`` and ``put_fact`` -- the JSONL-backed
``memory/facts.jsonl`` reader/writer. These functions are
touched by the agent-side chat scripts but were never
imported by the test suite.

The POSIX permission-bit check (``chmod 0o600``) only works
on POSIX filesystems -- Windows NTFS uses ACLs. The
permission assertion is therefore skipped on
``sys.platform == "win32"``.
"""
from __future__ import annotations

import json
import os
import stat
import sys
import tempfile
from pathlib import Path

import pytest

# Same POSIX-only check as test_arena_agent_helpers_files:
# NTFS ignores chmod, so the stat.S_IMODE == 0o600 assertion
# only makes sense on POSIX.
_POSIX_ONLY = pytest.mark.skipif(
    sys.platform == "win32",
    reason="POSIX permission bits (chmod 0o600) are not "
           "enforced on Windows NTFS",
)


_tmp_home = Path(tempfile.mkdtemp(prefix="arena_helpers_runtime_"))
_previous_home = os.environ.get("ARENA_AGENT_HOME")
os.environ["ARENA_AGENT_HOME"] = str(_tmp_home)

try:
    from arena.agent_helpers import runtime  # noqa: E402
finally:
    # Restored immediately: `files.ROOT` is evaluated at import, so the
    # variable has done its job by the line above. Kept set, it became
    # the ambient value for everything collected after this module,
    # under a randomised collection order (#348).
    #
    # In a `finally` because a failing import is exactly when this must
    # still happen: pytest reports the collection error and carries on
    # importing later modules, which would otherwise inherit the tmp
    # home -- the leak this file exists to remove, via the error path.
    #
    # Evicting the modules matters just as much. `files.ROOT` keeps
    # pointing at the tmp home for as long as the module object is
    # reachable, so a later importer is handed this module's tmp home
    # whatever the environment says by then; restoring the variable
    # alone does not undo that. `sys.modules` is not the only reference:
    # importing a submodule also binds it as an attribute of its parent
    # package, so `from arena.agent_helpers import files` would still
    # find the stale object. Both are dropped.
    for _bound_at_import in (
            "arena.agent_helpers.runtime", "arena.agent_helpers.files"):
        sys.modules.pop(_bound_at_import, None)
    for _parent, _child in (("arena.agent_helpers", "runtime"),
                            ("arena.agent_helpers", "files")):
        _package = sys.modules.get(_parent)
        if _package is not None:
            delattr_target = getattr(_package, _child, None)
            if delattr_target is not None:
                delattr(_package, _child)

    if _previous_home is None:
        os.environ.pop("ARENA_AGENT_HOME", None)
    else:
        os.environ["ARENA_AGENT_HOME"] = _previous_home


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


@_POSIX_ONLY
def test_put_fact_sets_owner_only_mode(monkeypatch, tmp_path):
    target = tmp_path / "facts.jsonl"
    monkeypatch.setattr(runtime, "FACTS", target)
    runtime.put_fact("k", "v")
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
