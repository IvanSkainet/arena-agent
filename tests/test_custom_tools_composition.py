"""v4.98.0 -- composition (multi-step) custom tools tests."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from arena.mcp import custom_tools as ct  # noqa: E402


@pytest.fixture()
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("ARENA_AGENT_HOME", str(tmp_path))
    ct._reset_cache()
    yield tmp_path
    ct._reset_cache()


def _mcp(text, is_error=False):
    return {"isError": is_error, "content": [{"type": "text", "text": text}]}


# ---------------------------------------------------------------------------
# pure helpers
# ---------------------------------------------------------------------------

def test_substitute_dotted_and_missing():
    ns = {"serial": "S", "steps": {"pc": {"version": "4.97.0", "host": "PC"}}}
    # exact token -> raw typed value
    assert ct._substitute("{steps.pc.version}", ns) == "4.97.0"
    # embedded -> stringified, missing -> empty
    assert ct._substitute("{serial}@{steps.pc.host}/{steps.missing}", ns) == "S@PC/"
    # nested structures recurse
    assert ct._substitute({"a": "{serial}", "b": ["{steps.pc.version}"]}, ns) == \
        {"a": "S", "b": ["4.97.0"]}


def test_validate_steps_ok_and_errors():
    static = {"sys.status", "exec.echo", "fs.read"}
    assert ct.validate_steps([{"id": "a", "tool": "sys.status", "args": {}}], static) is None
    assert ct.validate_steps([], static)  # empty
    assert ct.validate_steps([{"id": "1bad", "tool": "sys.status"}], static)  # bad id
    assert ct.validate_steps([{"id": "a", "tool": "sys.status"},
                              {"id": "a", "tool": "exec.echo"}], static)  # dup id
    assert ct.validate_steps([{"id": "a", "tool": "custom.x"}], static)  # recursion
    assert ct.validate_steps([{"id": "a", "tool": "custom.create"}], static)  # mgmt
    assert ct.validate_steps([{"id": "a", "tool": "no.such"}], static)  # unknown
    assert ct.validate_steps([{"id": "a", "tool": "sys.status", "args": "x"}], static)


def test_derived_risk_spec_max_over_steps():
    assert ct.derived_risk_spec({"steps": [{"tool": "fs.read"}, {"tool": "sys.status"}]}) == "safe"
    assert ct.derived_risk_spec({"steps": [{"tool": "fs.read"}, {"tool": "fs.create"}]}) == "medium"
    assert ct.derived_risk_spec({"steps": [{"tool": "fs.read"}, {"tool": "exec.exec"}]}) == "dangerous"
    # unknown step -> at least medium
    assert ct.derived_risk_spec({"steps": [{"tool": "totally.made_up"}]}) == "medium"
    # single-call shape still works
    assert ct.derived_risk_spec({"call": {"tool": "fs.read"}}) == "safe"


# ---------------------------------------------------------------------------
# run_steps: data flow, continue-on-error, composite ok
# ---------------------------------------------------------------------------

def test_run_steps_data_flow():
    spec = {"steps": [
        {"id": "pc", "tool": "sys.status", "args": {}},
        {"id": "echo", "tool": "exec.echo", "args": {"text": "v={steps.pc.version}"}},
    ]}
    calls = []

    def call_tool(name, args):
        calls.append((name, args))
        if name == "sys.status":
            return _mcp(json.dumps({"ok": True, "version": "4.97.0"}))
        return _mcp(args.get("text", ""))  # exec.echo

    out = json.loads(ct.run_steps(spec, {"serial": "S"}, call_tool)["content"][0]["text"])
    assert calls[0] == ("sys.status", {})
    assert calls[1] == ("exec.echo", {"text": "v=4.97.0"})  # dotted substitution
    assert out["ok"] is True
    assert out["steps"]["pc"] == {"ok": True, "version": "4.97.0"}
    assert out["steps"]["echo"] == "v=4.97.0"
    assert out["step_ok"] == {"pc": True, "echo": True}


def test_run_steps_continue_on_error_marks_composite_not_ok():
    spec = {"steps": [
        {"id": "good", "tool": "sys.status", "args": {}},
        {"id": "bad", "tool": "fs.read", "args": {"path": "/x"}},
    ]}

    def call_tool(name, args):
        if name == "fs.read":
            return _mcp(json.dumps({"ok": False, "error": "boom"}))
        return _mcp(json.dumps({"ok": True}))

    out = json.loads(ct.run_steps(spec, {}, call_tool)["content"][0]["text"])
    assert out["ok"] is False  # one step failed
    assert out["step_ok"] == {"good": True, "bad": False}
    assert out["steps"]["good"] == {"ok": True}  # good step result preserved


def test_run_steps_halt_blocks_mid_pipeline_via_call_tool():
    # The halt gate lives in call_tool; a halted mutating step returns an
    # isError block -> that step is not-ok, composite not-ok, pipeline keeps
    # going (continue-on-error) but every mutating step is blocked.
    spec = {"steps": [
        {"id": "a", "tool": "exec.exec", "args": {"cmd": "whoami"}},
        {"id": "b", "tool": "exec.exec", "args": {"cmd": "id"}},
    ]}
    blocked = _mcp(json.dumps({"ok": False, "error": "agent_halted",
                               "message": "BLOCKED while agent is halted"}), is_error=True)
    seen = []

    def call_tool(name, args):
        seen.append(args["cmd"])
        return blocked

    out = json.loads(ct.run_steps(spec, {}, call_tool)["content"][0]["text"])
    assert seen == ["whoami", "id"]  # both attempted (continue-on-error)
    assert out["ok"] is False
    assert out["step_ok"] == {"a": False, "b": False}


# ---------------------------------------------------------------------------
# create / persist / dispatch
# ---------------------------------------------------------------------------

def test_create_composite_persists_with_max_risk(home):
    res = ct.create_tool(
        "ship_status", "PC + phone", {"properties": {"serial": {"type": "string"}},
                                      "required": ["serial"]},
        steps=[{"id": "pc", "tool": "sys.status", "args": {}},
               {"id": "phone", "tool": "mobile.info", "args": {"serial": "{serial}"}}],
    )
    assert res["ok"], res
    spec = res["tool"]
    assert "steps" in spec and "call" not in spec
    assert spec["risk"] == "safe"  # both steps safe
    assert ct.risk_of("custom.ship_status") == "safe"
    # round-trip from disk
    assert ct.get_tool("ship_status")["steps"][1]["args"] == {"serial": "{serial}"}


def test_create_rejects_both_or_neither_body(home):
    neither = ct.create_tool("x", "", {"properties": {}}, call=None, steps=None)
    assert not neither["ok"]
    both = ct.create_tool("x", "", {"properties": {}},
                          call={"tool": "sys.status"},
                          steps=[{"id": "a", "tool": "sys.status"}])
    assert not both["ok"]


def test_create_rejects_steps_using_custom_tool(home):
    res = ct.create_tool("x", "", {"properties": {}},
                         steps=[{"id": "a", "tool": "custom.other"}])
    assert not res["ok"]


def test_create_rejects_input_named_steps(home):
    res = ct.create_tool("x", "", {"properties": {"steps": {"type": "string"}}},
                         call={"tool": "sys.status"})
    assert not res["ok"] and "reserved" in res["error"]


def test_handle_dispatch_runs_composite(home):
    ct.create_tool("gather", "", {"properties": {}},
                   steps=[{"id": "p", "tool": "sys.status", "args": {}}])
    seen = []

    class Ctx:
        def call_tool(self, name, args):
            seen.append(name)
            return _mcp(json.dumps({"ok": True, "version": "X"}))

    out = ct.handle_custom_tool("custom.gather", {}, ctx=Ctx())
    parsed = json.loads(out["content"][0]["text"])
    assert seen == ["sys.status"]
    assert parsed["ok"] is True and parsed["steps"]["p"] == {"ok": True, "version": "X"}


def test_single_call_still_works(home):
    """Backward compatibility: the v4.96.0 single-call shape is untouched."""
    res = ct.create_tool("reader", "", {"properties": {"p": {"type": "string"}},
                                        "required": ["p"]},
                         call={"tool": "fs.read", "args": {"path": "{p}"}})
    assert res["ok"] and "call" in res["tool"] and res["tool"]["risk"] == "safe"
    wrapped, wargs = ct.expand(res["tool"], {"p": "/etc/x"})
    assert wrapped == "fs.read" and wargs == {"path": "/etc/x"}


def test_tool_def_summary_distinguishes_composite(home):
    ct.create_tool("c", "", {"properties": {}},
                   steps=[{"id": "a", "tool": "sys.status"},
                          {"id": "b", "tool": "fs.read", "args": {"path": "/x"}}])
    defs = {d["name"]: d for d in ct.tool_defs()}
    assert "composite of 2 step(s)" in defs["custom.c"]["description"]
    assert "[a, b]" in defs["custom.c"]["description"]


# fs.read + sys.status are both safe -> risk safe; fix the assertion above:
def test_tool_def_composite_risk_safe(home):
    ct.create_tool("c2", "", {"properties": {}},
                   steps=[{"id": "a", "tool": "sys.status"},
                          {"id": "b", "tool": "fs.read", "args": {"path": "/x"}}])
    defs = {d["name"]: d for d in ct.tool_defs()}
    assert "risk: safe" in defs["custom.c2"]["description"]


# ---------------------------------------------------------------------------
# v4.99 -- library reuse (custom tool referencing custom tool) + recursion cap
# ---------------------------------------------------------------------------

class _DispatchCtx:
    """ctx.call_tool that re-enters handle_custom_tool for custom.* names
    (mirrors the real dispatcher) and fakes built-ins."""
    def __init__(self, static_handler):
        self._static = static_handler
        self.calls = []

    def call_tool(self, name, args):
        self.calls.append((name, args))
        if name.startswith("custom."):
            return ct.handle_custom_tool(name, args, ctx=self)
        return self._static(name, args)


def test_library_custom_ref_allowed_and_risk_propagates(home):
    lib = ct.create_tool("lib", "", {"properties": {}},
                         call={"tool": "sys.status"})  # safe
    assert lib["ok"], lib
    comp = ct.create_tool("uses_lib", "", {"properties": {}},
                          steps=[{"id": "a", "tool": "custom.lib"}])
    assert comp["ok"], comp
    assert comp["tool"]["risk"] == "safe"
    assert ct.risk_of("custom.uses_lib") == "safe"
    # a chain that touches a medium tool anywhere becomes medium
    comp2 = ct.create_tool("uses_lib2", "", {"properties": {}},
                           steps=[{"id": "a", "tool": "custom.lib"},
                                  {"id": "b", "tool": "fs.create",
                                   "args": {"path": "/x", "content": "y"}}])
    assert comp2["ok"] and comp2["tool"]["risk"] == "medium"


def test_create_rejects_self_reference(home):
    res = ct.create_tool("me", "", {"properties": {}},
                         steps=[{"id": "a", "tool": "custom.me"}])
    assert not res["ok"] and ("itself" in res["error"] or "not defined" in res["error"])


def test_create_rejects_undefined_custom_ref(home):
    res = ct.create_tool("x", "", {"properties": {}},
                         steps=[{"id": "a", "tool": "custom.nope"}])
    assert not res["ok"] and "not defined" in res["error"]


def test_create_rejects_cycle_via_remove_recreate(home):
    a = ct.create_tool("a", "", {"properties": {}}, call={"tool": "sys.status"})
    b = ct.create_tool("b", "", {"properties": {}},
                       steps=[{"id": "a", "tool": "custom.a"}])
    assert a["ok"] and b["ok"]
    ct.remove_tool("a")
    cyc = ct.create_tool("a", "", {"properties": {}},
                         steps=[{"id": "b", "tool": "custom.b"}])  # a->b->a cycle
    assert not cyc["ok"] and "cycle" in cyc["error"]


def test_nested_custom_call_actually_runs(home):
    ct.create_tool("lib", "", {"properties": {"msg": {"type": "string"}},
                               "required": ["msg"]},
                   call={"tool": "exec.echo", "args": {"text": "{msg}"}})
    ct.create_tool("outer", "", {"properties": {}},
                   steps=[{"id": "r", "tool": "custom.lib", "args": {"msg": "hello"}}])

    def static(name, args):
        return _mcp(args.get("text", ""))  # exec.echo

    ctx = _DispatchCtx(static)
    out = ct.handle_custom_tool("custom.outer", {}, ctx=ctx)
    parsed = json.loads(out["content"][0]["text"])
    assert parsed["ok"] is True
    assert parsed["steps"]["r"] == "hello"
    assert ("exec.echo", {"text": "hello"}) in ctx.calls  # inner built-in reached


def test_recursion_depth_guard(home, monkeypatch):
    monkeypatch.setattr(ct, "MAX_CUSTOM_DEPTH", 2)
    ct.create_tool("t1", "", {"properties": {}}, call={"tool": "sys.status"})
    ct.create_tool("t2", "", {"properties": {}},
                   steps=[{"id": "a", "tool": "custom.t1"}])
    ct.create_tool("t3", "", {"properties": {}},
                   steps=[{"id": "b", "tool": "custom.t2"}])
    ctx = _DispatchCtx(lambda name, args: _mcp(json.dumps({"ok": True})))
    out = ct.handle_custom_tool("custom.t3", {}, ctx=ctx)
    text = out["content"][0]["text"]
    assert "recursion depth" in text  # depth cap tripped inside the tree


def test_unresolved_placeholder_leaves_side_effects_behind():
    """A bad placeholder does not stop the run — later steps still fire.

    Found by dogfooding the core/build-capability skill: a composition wired
    ``{steps.src.content}`` at a step whose tool returns a plain string, so the
    placeholder resolved to nothing, ``fs.write`` was still called, and it
    created an EMPTY file. The run reported ``ok: false`` afterwards, but the
    side effect was already on disk.

    Continue-on-error is deliberate (see the HALT test above: every hop is
    blocked at the chokepoint, so the loop does not need to stop). This test
    pins the consequence so nobody "fixes" the empty write by making the loop
    abort, and so the behaviour authors must design around stays documented.
    """
    spec = {"steps": [
        {"id": "src", "tool": "fs.read", "args": {"path": "/note.txt"}},
        # .content does not exist on a plain-string step result
        {"id": "put", "tool": "fs.write", "args": {"path": "/copy.txt",
                                                   "content": "{steps.src.content}"}},
        {"id": "after", "tool": "sys.status", "args": {}},
    ]}
    calls = []

    def call_tool(name, args):
        calls.append((name, args))
        if name == "fs.read":
            return _mcp("plain text, not an object")
        if name == "fs.write":
            # mirrors the real handler: a None content is a type error
            if args.get("content") in (None, "", "{steps.src.content}"):
                return _mcp("ERROR: TypeError: write() argument must be str, not None",
                            is_error=True)
            return _mcp(json.dumps({"ok": True}))
        return _mcp(json.dumps({"ok": True}))

    out = json.loads(ct.run_steps(spec, {}, call_tool)["content"][0]["text"])

    assert out["ok"] is False
    assert out["step_ok"]["src"] is True
    assert out["step_ok"]["put"] is False
    # the step AFTER the failure still ran — that is the property to remember
    assert out["step_ok"]["after"] is True
    assert [c[0] for c in calls] == ["fs.read", "fs.write", "sys.status"]


def test_whole_step_placeholder_carries_plain_string_output():
    """`{steps.<id>}` is the working form for tools that return plain text."""
    spec = {"steps": [
        {"id": "src", "tool": "fs.read", "args": {"path": "/note.txt"}},
        {"id": "put", "tool": "fs.write", "args": {"path": "/copy.txt",
                                                   "content": "{steps.src}"}},
    ]}
    written = {}

    def call_tool(name, args):
        if name == "fs.read":
            return _mcp("capability built at runtime\n")
        written.update(args)
        return _mcp(json.dumps({"ok": True}))

    out = json.loads(ct.run_steps(spec, {}, call_tool)["content"][0]["text"])
    assert out["ok"] is True
    assert written["content"] == "capability built at runtime\n"
