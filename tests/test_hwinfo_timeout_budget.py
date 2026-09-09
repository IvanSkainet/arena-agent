"""The inner worst case must stay under every outer budget.

Why this gate exists
--------------------
`hwinfo.py --full` fires ~10 PowerShell `Get-CimInstance` queries. Each had a
30 s timeout, while `tests/test_project_modularity.py` gave the whole process
30 s. An outer budget smaller than the inner worst case does not fail loudly --
it fails *sometimes*, on whichever CI runner happens to be contended, and
reads like a flake. It failed twice on windows-latest before being traced.

So the constants are not the contract; the *relationship* between them is, and
that is what is pinned here. Raising `PS_PASS_BUDGET_S` past a caller's budget
fails this test rather than surfacing months later as an intermittent red.

Green here does not prove hwinfo collects anything: no Linux runner has WMI.
It proves the budgets cannot silently invert again.
"""
from __future__ import annotations

import ast
import re
import subprocess
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from arena.agentctl_extras import status  # noqa: E402
from arena.system import hwinfo_cim  # noqa: E402

REPO = Path(__file__).resolve().parents[1]

# Every caller that subprocesses a full hwinfo pass. The bound itself lives in
# `arena.agentctl_extras.status` and is imported by both callers, so there is
# one number rather than a table that has to be kept in step with the source.
# The earlier version of this file duplicated the literal here and used `ast`
# to check the copy still matched -- machinery whose only job was to detect
# drift that a shared constant cannot have.
HWINFO_CALLERS = (
    "arena/agentctl_extras/status.py",
    "tests/test_project_modularity.py",
)


def test_pass_budget_fits_inside_the_outer_budget():
    """The collector's own budget has to leave room for everything else.

    PS_PASS_BUDGET_S bounds the PowerShell queries only. Interpreter
    startup, imports and JSON serialisation are outside it, and on a
    contended windows-latest runner they are what consumed the old 10 s of
    headroom (#323).
    """
    worst = hwinfo_cim.PS_PASS_BUDGET_S
    outer = status.HWINFO_SUBPROCESS_TIMEOUT_S
    assert worst < outer, (
        f"hwinfo pass budget {worst}s does not fit inside the {outer}s "
        "subprocess bound"
    )
    assert outer - worst >= 30, (
        f"only {outer - worst}s of headroom between the {worst}s pass budget "
        f"and the {outer}s outer bound. Startup and serialisation live in "
        "that gap, and 10s of it was not enough on windows-latest (#323)"
    )


# The one name a hwinfo call site may bind `timeout=` to.
_REQUIRED_BOUND = "HWINFO_SUBPROCESS_TIMEOUT_S"


def test_every_hwinfo_call_binds_the_shared_bound():
    """Not merely "no literal" -- that name, specifically.

    Rejecting literals is not enough. `status.py` also defines
    TAILSCALE_STATUS_TIMEOUT_S = 10, and a call site could bind that by
    mistake: it is a named constant, so a literal check passes, and it is
    below PS_PASS_BUDGET_S, so the collector would be killed mid-pass on
    every slow run. That is the drift of #323 restored under a different
    spelling, which is why the name is asserted and not just the shape.
    """
    offenders = []
    for relative in HWINFO_CALLERS:
        source = (REPO / relative).read_text(encoding="utf-8")
        for node in _hwinfo_run_calls(source):
            bound = _timeout_argument(node)
            if bound != _REQUIRED_BOUND:
                offenders.append(f"{relative}:{node.lineno} timeout={bound}")
    assert not offenders, (
        f"hwinfo subprocess calls must pass timeout={_REQUIRED_BOUND}; "
        f"found: {offenders}"
    )


def test_the_bound_is_not_aliased_to_something_smaller():
    """Checking the name at the call site is not enough on its own.

    `from ... import TAILSCALE_STATUS_TIMEOUT_S as HWINFO_SUBPROCESS_TIMEOUT_S`
    satisfies the call-site check while binding 10 s -- below the 20 s pass
    budget. So the import has to be checked too: whatever the callers bind
    under this name must be the constant of that name.
    """
    for relative in HWINFO_CALLERS:
        source = (REPO / relative).read_text(encoding="utf-8")
        for node in ast.walk(ast.parse(source)):
            if not isinstance(node, ast.ImportFrom):
                continue
            for alias in node.names:
                if alias.asname == _REQUIRED_BOUND:
                    assert alias.name == _REQUIRED_BOUND, (
                        f"{relative}:{node.lineno} imports {alias.name} under "
                        f"the name {_REQUIRED_BOUND}. The call site then looks "
                        "correct while binding a different, smaller bound."
                    )


def _timeout_argument(call: ast.Call) -> str | None:
    """How `timeout=` is written at this call site, as source text."""
    for keyword in call.keywords:
        if keyword.arg != "timeout":
            continue
        if isinstance(keyword.value, ast.Name):
            return keyword.value.id
        if isinstance(keyword.value, ast.Attribute):
            return keyword.value.attr
        if isinstance(keyword.value, ast.Constant):
            return repr(keyword.value.value)
        return ast.dump(keyword.value)
    return None


def test_the_caller_scan_finds_something_in_every_caller():
    """A matcher that quietly matches nothing would make the gate vacuous.

    Both callers build argv from a local variable, so the hwinfo call is
    recognised by the enclosing function rather than by a literal argument
    -- and that kind of matching fails silently when a name changes. This
    is the tripwire for that: it caught the first version of the scan,
    which looked for a variable named `checks` while the loop actually
    passes `cmd`.
    """
    for relative in HWINFO_CALLERS:
        source = (REPO / relative).read_text(encoding="utf-8")
        assert _hwinfo_run_calls(source), (
            f"no hwinfo subprocess call found in {relative} -- the scan is "
            "looking for the wrong thing and the literal check above is "
            "passing on nothing"
        )


# The functions that shell out to hwinfo, by name. Identifying the call by its
# enclosing function survives a rename of the argv variable; matching on the
# variable did not.
_HWINFO_CALL_SITES = ("run_status", "test_modularized_cli_wrappers_import_cleanly")


def _hwinfo_run_calls(source: str) -> list[ast.Call]:
    """Every `subprocess.run(...)` inside a function that runs hwinfo."""
    calls: list[ast.Call] = []
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.FunctionDef) or node.name not in _HWINFO_CALL_SITES:
            continue
        calls.extend(sub for sub in ast.walk(node) if _is_hwinfo_run(sub))
    return calls


def _is_hwinfo_run(node: ast.AST) -> bool:
    """A `subprocess.run(...)` whose argv is an hwinfo command."""
    if not isinstance(node, ast.Call):
        return False
    if not isinstance(node.func, ast.Attribute) or node.func.attr != "run":
        return False
    return _runs_hwinfo(node)


# argv variables that hold an hwinfo command at the two call sites. Matching
# the enclosing function alone swept up the neighbouring tailscale and git
# calls, which legitimately carry their own small literals; matching on the
# string "hwinfo" inside the call matched nothing, because both sites build
# argv in a variable. The variable name is the thing that actually
# identifies these two calls.
_HWINFO_ARGV_NAMES = {"hw_script", "cmd"}


def _runs_hwinfo(call: ast.Call) -> bool:
    """Whether this `subprocess.run(...)` passes an hwinfo argv."""
    if not call.args:
        return False
    mentioned = {
        node.id
        for node in ast.walk(call.args[0])
        if isinstance(node, ast.Name)
    }
    return bool(mentioned & _HWINFO_ARGV_NAMES)


def test_per_call_timeout_is_smaller_than_the_pass_budget():
    assert hwinfo_cim.PS_TIMEOUT_S < hwinfo_cim.PS_PASS_BUDGET_S


def test_no_powershell_call_hardcodes_a_timeout_above_the_per_call_budget():
    """Catch a call site that passes its own oversized timeout=."""
    src = (REPO / "arena" / "system" / "hwinfo_cim.py").read_text(encoding="utf-8")
    for match in re.finditer(r"_run_powershell\([^)]*timeout\s*=\s*(\d+)", src, re.S):
        assert int(match.group(1)) <= hwinfo_cim.PS_TIMEOUT_S, match.group(0)


# ---------------------------------------------------------------------------
# The budget actually clamps, on any OS (subprocess.run is stubbed)
# ---------------------------------------------------------------------------

def test_exhausted_pass_budget_short_circuits_without_spawning(monkeypatch):
    spawned = []

    def fake_run(*args, **kwargs):
        spawned.append(kwargs.get("timeout"))
        return subprocess.CompletedProcess(args=args, returncode=0, stdout="{}", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    hwinfo_cim.begin_pass(budget_s=0)
    try:
        res = hwinfo_cim._run_powershell("Get-CimInstance Win32_BIOS")
    finally:
        hwinfo_cim.end_pass()
    assert spawned == [], "budget was spent, yet a process was still spawned"
    assert res.returncode == 1
    assert res.stdout == ""
    assert "budget" in res.stderr


def test_call_timeout_is_clamped_to_the_remaining_budget(monkeypatch):
    seen = []

    def fake_run(*args, **kwargs):
        seen.append(kwargs.get("timeout"))
        return subprocess.CompletedProcess(args=args, returncode=0, stdout="{}", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    hwinfo_cim.begin_pass(budget_s=2)
    try:
        hwinfo_cim._run_powershell("Get-CimInstance Win32_BIOS")
    finally:
        hwinfo_cim.end_pass()
    assert seen and seen[0] <= 2, seen


def test_outside_a_pass_the_default_timeout_applies(monkeypatch):
    seen = []

    def fake_run(*args, **kwargs):
        seen.append(kwargs.get("timeout"))
        return subprocess.CompletedProcess(args=args, returncode=0, stdout="{}", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    hwinfo_cim.end_pass()
    hwinfo_cim._run_powershell("Get-CimInstance Win32_BIOS")
    assert seen == [float(hwinfo_cim.PS_TIMEOUT_S)]


def test_a_pass_is_closed_even_when_collection_raises(monkeypatch):
    """A leaked deadline would silently starve the next pass."""
    from arena.system import hwinfo_collect

    def boom():
        raise RuntimeError("collection blew up")

    monkeypatch.setattr(hwinfo_collect, "_collect_full_inner", boom)
    with pytest.raises(RuntimeError):
        hwinfo_collect.collect_full()
    assert hwinfo_cim._pass_deadline is None


def test_ten_starved_queries_finish_well_inside_the_outer_budget(monkeypatch):
    """End-to-end shape of the original bug, with a stubbed slow PowerShell."""
    def slow_run(*args, **kwargs):
        # Simulate a wedged WMI service: always burn the whole allowance.
        time.sleep(min(0.02, float(kwargs.get("timeout") or 0)))
        raise subprocess.TimeoutExpired(cmd="powershell.exe", timeout=kwargs.get("timeout"))

    monkeypatch.setattr(subprocess, "run", slow_run)
    monkeypatch.setattr(hwinfo_cim, "PS_TIMEOUT_S", 8)

    calls = 0
    started = time.monotonic()
    hwinfo_cim.begin_pass(budget_s=0.05)
    try:
        for _ in range(10):
            calls += 1
            try:
                hwinfo_cim._run_powershell("Get-CimInstance Win32_BIOS")
            except subprocess.TimeoutExpired:
                pass
    finally:
        hwinfo_cim.end_pass()
    elapsed = time.monotonic() - started
    assert calls == 10
    # Without the pass budget this would be 10 x per-call timeout.
    assert elapsed < 1.0, elapsed
