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

from arena.system import hwinfo_cim  # noqa: E402

REPO = Path(__file__).resolve().parents[1]

# Every outer budget that wraps a full hwinfo pass, with where it comes from.
# Add a row when a new caller subprocesses hwinfo.
OUTER_BUDGETS = {
    "tests/test_project_modularity.py::test_modularized_cli_wrappers_import_cleanly": 30,
}


def test_pass_budget_fits_inside_every_outer_budget():
    worst = hwinfo_cim.PS_PASS_BUDGET_S
    for where, outer in OUTER_BUDGETS.items():
        assert worst < outer, (
            f"hwinfo worst case {worst}s does not fit in the {outer}s budget at {where}"
        )


def test_outer_budget_table_matches_the_real_test_source():
    """The table above must not drift from the caller it claims to describe.

    A stale table would let this gate pass while the real caller shrank its
    timeout -- the failure mode this file exists to prevent.
    """
    src = (REPO / "tests" / "test_project_modularity.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    found = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef):
            continue
        if node.name != "test_modularized_cli_wrappers_import_cleanly":
            continue
        for sub in ast.walk(node):
            if isinstance(sub, ast.Call) and isinstance(sub.func, ast.Attribute) and sub.func.attr == "run":
                for kw in sub.keywords:
                    if kw.arg == "timeout" and isinstance(kw.value, ast.Constant):
                        found.append(kw.value.value)
    assert found, "could not find the subprocess timeout in the caller"
    declared = OUTER_BUDGETS["tests/test_project_modularity.py::test_modularized_cli_wrappers_import_cleanly"]
    assert set(found) == {declared}, f"caller uses {found}, table says {declared}"


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
