"""Every declared MCP tool must be reachable and must answer in words.

The existing MCP contract tests (``test_mcp_tool_contracts.py``,
``test_mcp_input_schema_validation.py``) are static: they scan the AST for
tool-name literals and validate the JSON Schema of each declaration.  Both
pass on a tool whose handler is missing, whose handler raises on every call,
or whose error is an exception with no message.  Nothing had ever *called*
the 234 tools we advertise to a model.

This test does.  It builds the real ``call_tool`` dispatcher from
``make_mcp_tool_runtime`` with a stub context and invokes every tool in
``MCP_TOOLS`` with empty arguments, then asserts two properties.  Neither
property is "the tool succeeds" -- with no arguments almost nothing can, and
asserting success would only test the stubs.

Property 1 -- reachability.  No tool may answer ``Unknown tool: <name>``.
That string means the tool is declared in ``MCP_TOOLS`` (so a model is told
it exists and will call it) but no branch of the dispatcher claims the name.
A rename on one side of the pair produces exactly this, silently.

Property 2 -- the refusal has to say something.  The dispatcher wraps the
whole handler chain in ``except Exception`` and renders it as
``ERROR: <Type>: <str(exc)>``.  When the exception carries no message that
renders as ``ERROR: FileNotFoundError:`` -- a dead end for the caller, which
cannot tell a missing argument from a missing file from a bug.  Found live:
five ``mission.autopilot_*`` tools did this for every call, because
``_load`` raised ``FileNotFoundError(run_id)`` and run_id was empty.

Property 3 -- no TypeError/AttributeError escaping the handler.  Those are
never a legitimate answer to a well-formed call with missing arguments; they
mean the handler itself is broken before it ever validates input.  Found
live: ``capability_gap.promote`` raised ``TypeError: 'dict' object is not
callable`` on *every* invocation, from a stray pair of parens that called
the result of ``app_config()``.  It had never worked.

Sabotage-checked: reverting either fix, or deleting a handler branch, fails
this test.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from arena.mcp.tool_registry import MCP_TOOLS  # noqa: E402
from arena.mcp.tools import McpToolContext, make_mcp_tool_runtime  # noqa: E402

# Handler-internal failures that are a property of the *sandbox*, not of the
# code under test: these tools shell out to a helper binary or a loopback
# service that is legitimately absent in CI.  Kept as an explicit list so a
# new one cannot be added by accident -- adding a name here is a deliberate,
# reviewable act.
_ENVIRONMENT_DEPENDENT_PREFIXES = (
    "desktop.",
    "desktop_app.",
    "mobile.",
    "mission.",
    "browser.",
)

# Exception types that are always a bug in the handler rather than a refusal.
_NEVER_ACCEPTABLE = ("TypeError:", "AttributeError:", "NameError:",
                     "UnboundLocalError:", "IndexError:")


@pytest.fixture(scope="module")
def call_tool():
    home = tempfile.mkdtemp(prefix="mcp-dispatch-")
    os.environ["ARENA_AGENT_HOME"] = home
    root = Path(home)

    def _any(*a, **k):
        return {}

    ctx = McpToolContext(
        version="dispatch-contract",
        bin_dir=root, bridge_dir=root, reports_dir=root,
        subprocess_kwargs=_any,
        blocked_reason=lambda *a, **k: "blocked in contract test",
        first_word=lambda c, *a, **k: (str(c).split() or [""])[0],
        cautious_allow=set(),
        under_root=lambda *a, **k: True,
        write_fact=lambda *a, **k: None,
        load_facts=lambda *a, **k: [],
        recall_sync=_any, recall_digest_sync=_any,
        audit=lambda *a, **k: None, app_config=_any,
        common_status=_any, build_plan=_any,
        file_watch_list_sync=_any, file_watch_add_sync=_any,
        file_watch_remove_sync=_any,
        react_sync=_any, reflect_sync=_any,
        utc_now=lambda *a, **k: "1970-01-01T00:00:00+00:00",
        skills_list_sync_with_cache=_any, skills_run_sync=_any,
        play_beep_sync=_any, send_notification_sync=_any,
    )
    return make_mcp_tool_runtime(ctx).call_tool


def _text(result) -> str:
    try:
        return str(result["content"][0]["text"])
    except Exception:
        return json.dumps(result, ensure_ascii=False, default=str)


@pytest.mark.parametrize("name", sorted({t["name"] for t in MCP_TOOLS}))
def test_declared_tool_is_reachable_and_answers_in_words(call_tool, name):
    try:
        result = call_tool(name, {})
    except BaseException as exc:  # noqa: BLE001 -- the dispatcher promises not to
        pytest.fail(f"{name}: dispatcher let {type(exc).__name__} escape: {exc}")

    text = _text(result)

    assert not text.startswith("Unknown tool:"), (
        f"{name} is declared in MCP_TOOLS but no dispatcher branch claims it; "
        "a model will be told this tool exists and every call will fail"
    )

    if text.startswith("ERROR: "):
        body = text[len("ERROR: "):]
        # "SomeError:" with nothing after it tells the caller nothing.
        assert body.rstrip().rstrip(":") != body.split(":")[0] or body.split(":", 1)[-1].strip(), (
            f"{name} refused with an empty message ({text!r}); "
            "return a structured {'ok': false, 'error': ...} instead"
        )
        if not name.startswith(_ENVIRONMENT_DEPENDENT_PREFIXES):
            assert not any(body.startswith(bad) for bad in _NEVER_ACCEPTABLE), (
                f"{name} raised {body!r} on a call with no arguments; that is a "
                "broken handler, not input validation"
            )


def test_no_tool_is_declared_twice():
    names = [t["name"] for t in MCP_TOOLS]
    dupes = sorted({n for n in names if names.count(n) > 1})
    assert not dupes, f"duplicate tool declarations: {dupes}"


def test_the_probe_can_actually_fail(call_tool):
    """A gate that always says zero is indistinguishable from a passing one."""
    text = _text(call_tool("definitely.not_a_real_tool", {}))
    assert text.startswith("Unknown tool:"), (
        "the dispatcher no longer reports unknown tools, so property 1 above "
        "can never fail and this whole file is decorative"
    )
