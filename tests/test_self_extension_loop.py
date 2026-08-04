"""The agent must be able to grow its own toolset, end to end, unaided.

This is the property the whole "self-extending environment" idea rests on:
a model that needs a capability the bridge lacks should be able to write it,
prove it, publish it and then *call* it, without a human editing anything.
Every individual piece of that chain already had tests. The chain did not.

Driven as a model drives it -- through the real ``call_tool`` dispatcher --
because the two defects this test was written after were both invisible to
unit tests of the parts:

1. **The chain was broken by vocabulary.** ``code_project.*`` identifies a
   project as ``name`` (7 tools); ``tool_foundry.validate/publish`` call the
   same project ``project``. An agent that said ``project`` to ``write`` got
   back "project name must use only letters, digits, dot, underscore and
   dash" -- a validation error about an argument it had never sent, naming a
   rule its input did not violate. Nothing was broken in either handler; the
   surface simply disagreed with itself. Five namespaces carried the same
   split.

2. **The fence was reported as engaged when it could not run.** Sandbox
   support was decided by ``shutil.which("systemd-run")``, which answers "is
   it installed", not "does it work". In any context without a D-Bus session
   bus the binary exists and fails on every call, so the refusal surfaced
   later as a confusing child-process error instead of an honest "this fence
   is unavailable here".

Both are environment defects rather than missing features, which is exactly
the class this test exists to catch: the bridge being unpleasant to drive.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from arena.mcp.tools import (  # noqa: E402
    McpToolContext,
    _accept_synonyms,
    make_mcp_tool_runtime,
)

TOOL_SRC = "import sys, json\nn = len(sys.argv[1].split())\nprint(json.dumps({'words': n}))\n"

MANIFEST = {
    "name": "wordcount",
    "description": "Count words in a string.",
    "input_schema": {"properties": {"text": {"type": "string"}}, "required": ["text"]},
    "run": {"lang": "python3", "entry": "main.py", "argv": ["{text}"], "timeout": 30},
    "tests": [{"name": "basic", "args": {"text": "a b c"},
               "expect": {"ok": True, "stdout_contains": "3"}}],
}


@pytest.fixture
def runtime(monkeypatch, tmp_path):
    monkeypatch.setenv("ARENA_AGENT_HOME", str(tmp_path))
    from arena.autonomy import posture as P
    P._reset_cache()
    # The fence itself is not what this test is about, and CI has no usable
    # user bus; the point is the authoring chain, not the isolation layer.
    P.save_posture({**P.load_posture(), "sandbox": "off"})

    import arena.mcp.custom_tools as C
    C._reset_cache()

    def _any(*a, **k):
        return {}

    ctx = McpToolContext(
        version="self-extension", bin_dir=tmp_path, bridge_dir=tmp_path,
        reports_dir=tmp_path, subprocess_kwargs=_any,
        blocked_reason=lambda *a, **k: None,
        first_word=lambda c, *a, **k: (str(c).split() or [""])[0],
        cautious_allow=set(), under_root=lambda *a, **k: True,
        write_fact=lambda *a, **k: None, load_facts=lambda *a, **k: [],
        recall_sync=_any, recall_digest_sync=_any, audit=lambda *a, **k: None,
        app_config=_any, common_status=_any, build_plan=_any,
        file_watch_list_sync=_any, file_watch_add_sync=_any,
        file_watch_remove_sync=_any, react_sync=_any, reflect_sync=_any,
        utc_now=lambda *a, **k: "1970-01-01T00:00:00+00:00",
        skills_list_sync_with_cache=_any, skills_run_sync=_any,
        play_beep_sync=_any, send_notification_sync=_any,
    )
    yield make_mcp_tool_runtime(ctx)
    C._reset_cache()
    P._reset_cache()


def _call(rt, tool, args=None):
    raw = rt.call_tool(tool, args or {})["content"][0]["text"]
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {"ok": False, "_raw": raw}


def _tool_names(rt):
    listed = rt.handle_rpc({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    return {t["name"] for t in listed["result"]["tools"]}


def test_agent_can_author_prove_publish_and_call_its_own_tool(runtime):
    rt = runtime
    before = _tool_names(rt)
    assert "custom.wordcount" not in before

    steps = [
        ("create", "code_project.create", {"name": "wordcount"}),
        ("write code", "code_project.write",
         {"name": "wordcount", "path": "main.py", "content": TOOL_SRC}),
        ("run", "code_project.run",
         {"name": "wordcount", "lang": "python3", "entry": "main.py",
          "argv": ["hello brave new world"]}),
        ("manifest", "code_project.write",
         {"name": "wordcount", "path": ".arena-tool.json",
          "content": json.dumps(MANIFEST)}),
        ("validate", "tool_foundry.validate", {"project": "wordcount"}),
        ("publish", "tool_foundry.publish", {"project": "wordcount"}),
    ]
    for label, tool, args in steps:
        out = _call(rt, tool, args)
        assert out.get("ok") is not False, f"step '{label}' ({tool}) failed: {out}"

    after = _tool_names(rt)
    assert "custom.wordcount" in after, (
        f"the published tool never appeared in tools/list "
        f"(before {len(before)}, after {len(after)})")

    # The payoff: the agent calls what it just built.
    result = _call(rt, "custom.wordcount", {"text": "one two three four"})
    assert result.get("ok") is not False, result
    # Assert on what the tool computed, not on how the envelope is escaped.
    assert json.loads(result["stdout"])["words"] == 4, result


def test_the_chain_works_with_either_vocabulary(runtime):
    """`name` and `project` mean the same thing; both must drive the chain."""
    rt = runtime
    # Deliberately the *other* spelling at every step from the one above.
    assert _call(rt, "code_project.create", {"project": "vocab"}).get("ok") is not False
    out = _call(rt, "code_project.write",
                {"project": "vocab", "path": "main.py", "content": TOOL_SRC})
    assert out.get("ok") is not False, (
        f"code_project.write rejected 'project' as a synonym for 'name': {out}")
    assert _call(rt, "code_project.read",
                 {"project": "vocab", "path": "main.py"}).get("ok") is not False


def test_synonyms_never_overwrite_what_the_caller_actually_said():
    """A convenience that silently rewrites explicit input would be worse."""
    both = _accept_synonyms("code_project.write", {"name": "a", "project": "b"})
    assert both["name"] == "a" and both["project"] == "b"

    one = _accept_synonyms("tool_foundry.validate", {"project": "x"})
    assert one["name"] == "x" and one["project"] == "x"

    # Unrelated namespaces must not have their arguments invented for them.
    untouched = _accept_synonyms("fs.read", {"path": "/tmp/x"})
    assert "name" not in untouched and "project" not in untouched


def test_publish_still_refuses_a_tool_whose_tests_fail(runtime):
    """A gate that publishes anything would make the chain worthless."""
    rt = runtime
    _call(rt, "code_project.create", {"name": "liar"})
    _call(rt, "code_project.write",
          {"name": "liar", "path": "main.py",
           "content": "print('nowhere near the expected output')\n"})
    bad = dict(MANIFEST, name="liar")
    _call(rt, "code_project.write",
          {"name": "liar", "path": ".arena-tool.json", "content": json.dumps(bad)})

    out = _call(rt, "tool_foundry.publish", {"project": "liar"})
    assert out.get("ok") is False, f"published a tool whose declared test fails: {out}"
    assert "custom.liar" not in _tool_names(rt)


def test_an_unavailable_fence_refuses_with_a_reason_and_a_remedy(monkeypatch):
    """Fail-closed must mean the fence works, not that it is installed."""
    from arena.autonomy import runner

    monkeypatch.setattr(runner, "_have", lambda _n: True)
    monkeypatch.setattr(runner, "systemd_run_works",
                        lambda: (False, "Failed to connect to user scope bus"))

    out = runner.resolve("linux", {"sandbox": "systemd"})
    assert out["supported"] is False
    assert "cannot start a unit" in out["note"]
    assert out.get("remedy"), "a refusal without a route forward is a dead end"

    monkeypatch.setattr(runner, "systemd_run_works", lambda: (True, ""))
    assert runner.resolve("linux", {"sandbox": "systemd"})["supported"] is True
