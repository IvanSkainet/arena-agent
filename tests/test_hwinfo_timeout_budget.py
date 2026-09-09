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

# The module that defines it. Its own `HWINFO_SUBPROCESS_TIMEOUT_S = 60` is
# the single source the other callers import.
_DEFINING_MODULE = "arena/agentctl_extras/status.py"

# The same module as an import path. A caller importing this name from
# anywhere else has the right spelling and the wrong number (cubic).
_DEFINING_MODULE_IMPORT = "arena.agentctl_extras.status"


def test_every_hwinfo_call_binds_the_shared_bound():
    """Not merely "no literal" -- that name, specifically.

    Rejecting literals is not enough: a call site could bind some other
    named constant below PS_PASS_BUDGET_S, so a literal check would pass
    while the collector was still killed mid-pass. That is the drift of
    #323 restored under a different spelling, which is why the name is
    asserted and not just the shape.
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


def test_the_bound_is_not_rebound_to_something_smaller():
    """Checking the name at the call site is not enough on its own.

    The call site can be made to *look* right while binding 10 s, and there
    is more than one way to do it:

        from ... import SMALLER_TIMEOUT_S as HWINFO_SUBPROCESS_TIMEOUT_S
        import somewhere as HWINFO_SUBPROCESS_TIMEOUT_S
        HWINFO_SUBPROCESS_TIMEOUT_S = SMALLER_TIMEOUT_S

    The first version of this test only looked at `ast.ImportFrom`, so the
    plain assignment walked straight past it -- verified by mutation, the
    suite stayed green. Every binding of the name is checked now: whatever a
    caller binds under it must be the constant of that name, imported from
    the module that defines it.
    """
    for relative in HWINFO_CALLERS:
        if relative == _DEFINING_MODULE:
            # Where the constant is defined, `NAME = 60` is the definition,
            # not a rebinding. Everywhere else it is one.
            continue
        source = (REPO / relative).read_text(encoding="utf-8")
        for node in ast.walk(ast.parse(source)):
            _assert_binding_is_the_real_constant(node, relative)


def _assert_binding_is_the_real_constant(node: ast.AST, relative: str) -> None:
    """Fail if `node` binds the required name to anything else.

    Enumerating statement types is the wrong shape for this: the second
    version listed ast.Assign and cubic pointed out that annotated
    assignment, tuple unpacking, `for` and `with ... as` all bind a name
    too. Confirmed by mutation -- all four walked past the check.

    So the question asked here is not "which statement is this" but "does
    this node bind the name". Python answers that itself: every binding of
    a bare name is an ast.Name carrying ast.Store, whatever the statement
    around it. Imports are the one exception, since they bind through an
    alias rather than a Name node, so they stay a separate branch.
    """
    if isinstance(node, (ast.Import, ast.ImportFrom)):
        _assert_import_is_the_real_constant(node, relative)
    elif _is_local_rebinding(node):
        raise AssertionError(
            f"{relative}:{node.lineno} rebinds {_REQUIRED_BOUND} locally. "
            "The name must come from arena.agentctl_extras.status, so that "
            "the call site cannot look correct while holding a smaller bound."
        )


def _is_local_rebinding(node: ast.AST) -> bool:
    """Does this node bind the required name to something of its own?"""
    return (
        isinstance(node, ast.Name)
        and isinstance(node.ctx, ast.Store)
        and node.id == _REQUIRED_BOUND
    )


def _assert_import_is_the_real_constant(node: ast.AST, relative: str) -> None:
    """Fail if an import binds the required name to anything else.

    Both halves matter: the wrong name under the right alias, and the
    right name out of the wrong module. Either one leaves a call site that
    reads correctly and holds a smaller number.
    """
    module = getattr(node, "module", None)
    for alias in node.names:
        if (alias.asname or alias.name) != _REQUIRED_BOUND:
            continue
        if alias.name != _REQUIRED_BOUND:
            raise AssertionError(
                f"{relative}:{node.lineno} imports {alias.name} under the "
                f"name {_REQUIRED_BOUND}. The call site then looks correct "
                "while binding a different, smaller bound."
            )
        if module != _DEFINING_MODULE_IMPORT:
            raise AssertionError(
                f"{relative}:{node.lineno} imports {_REQUIRED_BOUND} from "
                f"{module!r}. The right name from the wrong module is the "
                "same failure as the wrong name: only "
                f"{_DEFINING_MODULE_IMPORT} defines this bound."
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
# the enclosing function alone swept up neighbouring subprocess calls with
# their own legitimate literals; matching on the string "hwinfo" inside the
# call matched nothing, because both sites build argv in a variable. The
# variable name is the thing that actually identifies these two calls.
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


# Every module the bound is supposed to protect. `status.py` is the one
# that shells out during `agentctl status`; the list is here so that a new
# unbounded call in a sibling is a failure rather than an omission.
_NO_UNBOUNDED_SUBPROCESS = ("arena/agentctl_extras/status.py",)

# Everything in `subprocess` that blocks until the child exits and accepts
# `timeout=`. The first version of the gate listed only `run` and
# `check_output`, and `status.py` had an unbounded `subprocess.call` in
# `cmd_ctx` the whole time -- the gate passed while claiming module-wide
# coverage (Aikido, cubic). `Popen` is deliberately absent: it does not
# block and takes no timeout, so it has to be bounded at its `wait`.
_BLOCKING_SUBPROCESS_CALLS = (
    "subprocess.run",
    "subprocess.call",
    "subprocess.check_call",
    "subprocess.check_output",
)


def test_no_subprocess_call_in_status_runs_without_a_timeout():
    """A bound that only some calls carry is not a bound.

    This exists because the branch lost the tailscale fix once already: an
    automated commit reverted it to

        subprocess.run("tailscale funnel status || tailscale serve status",
                       shell=True)

    -- shell form, no timeout at all -- and every test here stayed green,
    because they all ask about the hwinfo call sites specifically. A wedged
    tailscale daemon hangs `agentctl status` again, which is the failure
    #323 was filed about, restored in the neighbouring block.

    So the question is asked of the whole module: any `subprocess.run` that
    can block has to say for how long. Nothing here is timing-dependent --
    it reads the source -- so it costs nothing to keep.
    """
    offenders = []
    for relative in _NO_UNBOUNDED_SUBPROCESS:
        calls = _blocking_calls_in(relative)
        assert calls, (
            f"{relative}: no subprocess call found at all -- this scan has "
            "gone blind and would pass no matter what the module does"
        )
        offenders += [
            f"{relative}:{call.lineno} {reason}"
            for call in calls
            if (reason := _unbounded_reason(call))
        ]
    assert not offenders, (
        "every blocking subprocess call must carry a timeout; found: "
        f"{offenders}"
    )


def _blocking_calls_in(relative: str) -> list[ast.Call]:
    """Every call in this module that waits on a child process."""
    tree = ast.parse((REPO / relative).read_text(encoding="utf-8"))
    aliases = _subprocess_aliases(tree)
    return [
        node for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and _resolved_call_name(node.func, aliases) in _BLOCKING_SUBPROCESS_CALLS
    ]


def _unbounded_reason(call: ast.Call) -> str:
    """Why this call can wait forever, or "" if it cannot."""
    bound = next((kw for kw in call.keywords if kw.arg == "timeout"), None)
    if bound is None:
        return "no timeout"
    # `timeout=None` is what subprocess means by "wait forever". Spelling
    # the keyword is not the same as bounding the call.
    if isinstance(bound.value, ast.Constant) and bound.value.value is None:
        return "timeout=None"
    return ""


def test_status_does_not_reach_for_a_shell():
    """`shell=True` and a timeout do not compose.

    `subprocess.run(..., shell=True, timeout=N)` kills the shell it
    spawned, not the process underneath: the child is reparented and keeps
    running after the call has returned. So on this path a shell is not
    merely a lint preference -- it silently defeats the bound the test
    above checks for.
    """
    offenders = []
    for relative in _NO_UNBOUNDED_SUBPROCESS:
        source = (REPO / relative).read_text(encoding="utf-8")
        offenders += [
            f"{relative}:{node.lineno}"
            for node in ast.walk(ast.parse(source))
            if isinstance(node, ast.Call) and _asks_for_a_shell(node)
        ]
    assert not offenders, (
        "shell=True defeats the timeout, since it is the shell that gets "
        f"killed and not the child; found: {offenders}"
    )


def _asks_for_a_shell(call: ast.Call) -> bool:
    """Is `shell=` passed as anything other than a literal False?"""
    return any(
        keyword.arg == "shell"
        and not (isinstance(keyword.value, ast.Constant) and keyword.value.value is False)
        for keyword in call.keywords
    )


def _subprocess_aliases(tree: ast.Module) -> dict[str, str]:
    """Every local name that reaches into `subprocess`, mapped to it.

    `import subprocess as sp` and `from subprocess import call` both hide
    a blocking call from a scan that matches the literal text
    `subprocess.call` -- verified by mutation, both walked past the gate.
    The names a module chose are read from the module itself rather than
    assumed (cubic).
    """
    aliases: dict[str, str] = {}
    for node in ast.walk(tree):
        aliases.update(_aliases_from(node))
    return aliases


def _aliases_from(node: ast.AST) -> dict[str, str]:
    """What one import statement contributes to that mapping.

    `import subprocess as sp` binds the module; `from subprocess import
    run as r` binds one function. The target differs, so the two forms are
    read apart.
    """
    if isinstance(node, ast.Import):
        return _module_aliases(node)
    if isinstance(node, ast.ImportFrom):
        return _function_aliases(node)
    return {}


def _module_aliases(node: ast.Import) -> dict[str, str]:
    """Names bound to the `subprocess` module itself."""
    wanted = [a for a in node.names if a.name == "subprocess"]
    return {a.asname or a.name: "subprocess" for a in wanted}


def _function_aliases(node: ast.ImportFrom) -> dict[str, str]:
    """Names bound to functions taken out of `subprocess`."""
    if node.module != "subprocess":
        return {}
    return {a.asname or a.name: f"subprocess.{a.name}" for a in node.names}


def _resolved_call_name(func: ast.AST, aliases: dict[str, str]) -> str:
    """`subprocess.run` however this module happens to spell it."""
    if isinstance(func, ast.Name):
        return aliases.get(func.id, func.id)
    dotted = _dotted_name(func)
    head, _, rest = dotted.partition(".")
    if rest and head in aliases:
        return f"{aliases[head]}.{rest}"
    return dotted


def _dotted_name(node: ast.AST) -> str:
    """`subprocess.run` for an Attribute chain, `run` for a bare Name."""
    parts = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
    return ".".join(reversed(parts))
