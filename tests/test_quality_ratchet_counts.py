"""The quality ratchet must actually count what the tools report.

v4.157.0: `vulture_count()` filtered vulture's output with `": (" in ln`.
Vulture emits `path.py:12: unused import 'x' (90% confidence)` -- there is no
`: (` anywhere in that. So the filter matched nothing, the function returned 0
unconditionally, and the vulture half of the gate had never run: "vulture=0"
meant "not counting", not "clean".

It was found by sabotage (adding a dead import to bin/ and watching the
ratchet stay green while `python -m vulture` reported the finding), which is
the only reason it surfaced at all -- a gate that always says zero looks
exactly like a gate that is passing.

These tests pin the parser against real tool output instead of trusting a
substring, and pin the fail-closed behaviour that stops a future format change
from silently reproducing the bug.
"""
from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
_RATCHET = REPO / "scripts" / "quality_ratchet.py"


def _load():
    spec = importlib.util.spec_from_file_location("_quality_ratchet", _RATCHET)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_mod = _load()


REAL_VULTURE_LINES = [
    "bin/hooks_runner.py:163: unused import '_sab' (90% confidence)",
    "arena/x.py:12: unused variable 'foo' (100% confidence)",
    "scripts/y.py:1: unused function 'bar' (60% confidence)",
    "a/b/c.py:9999: unused attribute 'baz' (60% confidence)",
]

NOT_FINDINGS = [
    "",
    "Some header line",
    "arena/x.py:12 missing the colon-space marker",
    "/home/user/arena-agent/scripts/foo.py",
]


@pytest.mark.parametrize("line", REAL_VULTURE_LINES)
def test_parser_recognises_real_vulture_output(line):
    assert _mod._VULTURE_FINDING.match(line), f"not recognised as a finding: {line!r}"


@pytest.mark.parametrize("line", NOT_FINDINGS)
def test_parser_ignores_non_findings(line):
    assert not _mod._VULTURE_FINDING.match(line), f"wrongly counted: {line!r}"


def test_the_old_broken_filter_would_have_matched_nothing():
    """Documents the actual defect, so nobody 'simplifies' it back."""
    assert all(": (" not in line for line in REAL_VULTURE_LINES)


def test_vulture_count_agrees_with_the_tool_itself():
    """End-to-end: the ratchet's number must equal vulture's own line count."""
    proc = subprocess.run(
        [sys.executable, "-m", "vulture", "--min-confidence", "80"],
        cwd=REPO, capture_output=True, text=True,
    )
    if proc.returncode not in (0, 3):
        pytest.skip(f"vulture unavailable or misconfigured (rc={proc.returncode})")
    direct = [ln for ln in proc.stdout.splitlines()
              if _mod._VULTURE_FINDING.match(ln)]
    assert _mod.vulture_count() == len(direct)


def test_a_real_finding_is_actually_counted(monkeypatch):
    """The regression that matters: a finding must move the number off zero.

    On a clean tree both the correct parser and the old broken filter return
    0, so counting the current repo proves nothing. Feed the function real
    vulture output instead.
    """
    class _Proc:
        returncode = 3
        stdout = "\n".join(REAL_VULTURE_LINES) + "\n"
        stderr = ""

    monkeypatch.setattr(_mod, "run", lambda *a, **k: _Proc())
    assert _mod.vulture_count() == len(REAL_VULTURE_LINES)


def test_rc3_with_unparseable_output_fails_closed(monkeypatch):
    """A format change must abort, not report a clean tree."""
    class _Proc:
        returncode = 3
        stdout = "vulture 9.0 said something entirely new\n"
        stderr = ""

    monkeypatch.setattr(_mod, "run", lambda *a, **k: _Proc())
    with pytest.raises(SystemExit) as excinfo:
        _mod.vulture_count()
    assert excinfo.value.code == 2
