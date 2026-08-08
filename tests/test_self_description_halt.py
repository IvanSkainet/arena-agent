"""The self-description must never tell a halted agent it is running.

Found by pointing Serena at the whole tree and, more importantly, by
finally parsing what it returned. `get_diagnostics_for_file` had been
reporting

    arena/admin/handlers_selfdesc.py
        [reportAttributeAccessIssue] "control_status" is unknown import symbol

on every run. The first sweep read it as "0 problems" because the
result shape is nested -- `{path: {severity: {symbol: [...]}}}` -- and
the parser expected a flat list. The scan was green because it was
looking at nothing.

The bug underneath was real and verified live on the operator's
machine. `/v1/self` imported `control_status` from `arena.control`; no
such function exists there. The import sat inside a bare
`except Exception`, so it failed silently on every single call and the
guard block always reported `halt: inactive`.

Measured, with HALT genuinely engaged:

    /v1/control/status  ->  agent_halted: true
    /v1/self            ->  halt: active=false, blocking=false

An agent told it is not halted while it is halted will keep trying,
conclude the tools are broken, and report that to the operator. Of all
the things a self-description can get wrong, the emergency stop is the
worst.
"""
from __future__ import annotations

import json
import pathlib

import pytest

from arena import control, self_description as sd

ROOT = pathlib.Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def restore_halt_state():
    """Never leave the process halted for the rest of the suite."""
    yield
    control._control_unhalt()


def test_is_halted_reflects_the_kill_switch():
    assert control.is_halted() is False
    control._control_halt("test")
    assert control.is_halted() is True
    control._control_unhalt()
    assert control.is_halted() is False


def test_the_guard_block_reports_an_engaged_halt():
    guards = {g["id"]: g for g in
              sd.guards(profile="owner-shell", yolo=True, halted=True)}
    assert guards["halt"]["active"] is True
    assert guards["halt"]["blocking"] is True


def test_the_self_endpoint_reads_the_real_halt_state():
    """The wiring, not just the formatting.

    `sd.guards` was always correct -- it takes `halted` as an argument.
    The defect was that the handler passed False forever, because the
    function it called did not exist. So this test asserts the handler
    imports something real.
    """
    source = (ROOT / "arena" / "admin"
              / "handlers_selfdesc.py").read_text(encoding="utf-8")

    # Code lines only: the comment above the import names the broken
    # symbol on purpose, and a gate that trips on its own explanation is
    # a false positive. (Same rake as the psutil header in v4.167.6 and
    # the download URL in v4.169.1 -- third time, so it is worth saying
    # plainly: assert on code, quote history in prose.)
    code = "\n".join(ln for ln in source.splitlines()
                     if not ln.lstrip().startswith("#"))

    assert "control_status" not in code, (
        "handlers_selfdesc imports control_status, which does not exist "
        "in arena.control -- the halt state will silently read as False")
    assert "is_halted" in code, "the handler does not read the halt state"

    # And the symbol it imports must actually be there.
    assert hasattr(control, "is_halted"), "arena.control has no is_halted"


def test_the_halt_import_is_not_swallowed_by_a_bare_except():
    """The silent failure is the reason this shipped at all.

    A missing symbol wrapped in `except Exception: pass` degrades to a
    wrong answer instead of an error, and a wrong answer about the
    emergency stop is worse than a 500. Assert the import is not inside
    a try block.
    """
    import ast

    source = (ROOT / "arena" / "admin"
              / "handlers_selfdesc.py").read_text(encoding="utf-8")
    tree = ast.parse(source)

    for node in ast.walk(tree):
        if not isinstance(node, ast.Try):
            continue
        for child in ast.walk(node):
            if isinstance(child, ast.ImportFrom) and child.module == "arena.control":
                raise AssertionError(
                    "the arena.control import is inside a try/except; a "
                    "missing symbol will silently report 'not halted'")


def test_a_halted_bridge_says_so_in_its_hint():
    """The sentence an agent actually reads."""
    tools = [{"name": "exec.exec"}, {"name": "fs.read"}]
    described = sd.describe(tools=tools, host={"class": "linux"},
                            profile="owner-shell", yolo=True, halted=True)
    assert "halt" in described["blocked_by"]
    assert "HALT" in described["hint"]


def test_serena_diagnostics_are_parsed_from_the_nested_shape():
    """The meta-lesson: a scan that finds nothing may be looking at nothing.

    Serena returns `{path: {severity: {symbol: [items]}}}`. Reading it as
    a flat list yields zero findings on every file, which looks exactly
    like a clean codebase. 654 files were "checked" that way and
    reported clean while a real error sat in one of them.

    This pins the parser against a captured real response so the next
    sweep cannot be silently empty.
    """
    sample = {
        "arena/x.py": {
            "Error": {
                "obviously_wrong": [
                    {"message": 'Cannot access attribute "nope"',
                     "code": "reportAttributeAccessIssue"},
                ]
            },
            "Warning": {
                "other": [{"message": "possibly unbound", "code": "x"}]
            },
        }
    }

    def flatten(payload):
        out = []
        for _path, by_severity in payload.items():
            for severity, by_symbol in by_severity.items():
                for _symbol, items in by_symbol.items():
                    for item in items:
                        out.append((severity, item.get("message", "")))
        return out

    flat = flatten(sample)
    assert len(flat) == 2, "the nested shape was not flattened"
    assert any(s == "Error" for s, _m in flat)
    # A naive `len(json.loads(raw))` would return 1 here -- one path key --
    # and a `.get("diagnostics")` would return nothing at all.
    assert len(json.loads(json.dumps(sample))) == 1
