"""The CodeQL aggregate gate must fail closed.

CodeQL's four `Analyze (...)` checks were reporting on every commit while being
neither required nor aggregated, so a CodeQL failure could not block a merge.
The gate that fixes this is only worth having if it stays strict, so these
tests pin the three ways it could rot into a rubber stamp:

* a language failing must be red,
* a language never reporting must be red (not silently "clean"),
* nothing reporting at all must be red.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

GATE = Path(__file__).resolve().parents[1] / ".github" / "scripts" / "codeql_required_gate.py"


def _load():
    spec = importlib.util.spec_from_file_location("codeql_required_gate", GATE)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture()
def gate():
    return _load()


def _completed(names, conclusion="success"):
    return [{"name": n, "status": "completed", "conclusion": conclusion} for n in names]


def test_gate_script_exists():
    assert GATE.is_file(), f"{GATE} is missing; the CodeQL gate cannot run"


def test_all_languages_pass_is_green(gate, monkeypatch):
    monkeypatch.setattr(gate, "_checks", lambda sha: _completed(gate.EXPECTED))
    assert gate.main(["--sha", "deadbeef", "--timeout", "0", "--poll", "0"]) == 0


def test_one_language_failing_is_red(gate, monkeypatch):
    runs = _completed(gate.EXPECTED)
    runs[-1]["conclusion"] = "failure"
    monkeypatch.setattr(gate, "_checks", lambda sha: runs)
    assert gate.main(["--sha", "deadbeef", "--timeout", "0", "--poll", "0"]) == 1


def test_missing_language_is_red_not_green(gate, monkeypatch):
    """'Never ran' must never read as 'clean'."""
    monkeypatch.setattr(gate, "_checks", lambda sha: _completed(gate.EXPECTED[:-1]))
    assert gate.main(["--sha", "deadbeef", "--timeout", "0", "--poll", "0"]) == 1


def test_no_checks_at_all_is_red(gate, monkeypatch):
    monkeypatch.setattr(gate, "_checks", lambda sha: [])
    assert gate.main(["--sha", "deadbeef", "--timeout", "0", "--poll", "0"]) == 1


@pytest.mark.parametrize("conclusion", ["cancelled", "timed_out", "action_required", "stale", "skipped"])
def test_non_success_conclusions_are_red(gate, monkeypatch, conclusion):
    """A cancelled or stale analysis is an unknown, and unknown is not a pass."""
    runs = _completed(gate.EXPECTED)
    runs[0]["conclusion"] = conclusion
    monkeypatch.setattr(gate, "_checks", lambda sha: runs)
    assert gate.main(["--sha", "deadbeef", "--timeout", "0", "--poll", "0"]) == 1


def test_skipped_analysis_is_red(gate, monkeypatch):
    """`skipped` means the analysis did not run, which is not evidence of clean.

    Regression: `skipped` was originally in the PASS set, so a CodeQL analysis
    that never executed would have reported green.
    """
    runs = _completed(gate.EXPECTED)
    runs[0]["conclusion"] = "skipped"
    monkeypatch.setattr(gate, "_checks", lambda sha: runs)
    assert gate.main(["--sha", "deadbeef", "--timeout", "0", "--poll", "0"]) == 1


def test_skipped_not_in_pass_set(gate):
    assert "skipped" not in gate.PASS


def test_default_timeout_exceeds_observed_codeql_duration(gate):
    """CodeQL took >15 min on PR #216 and the gate timed out on a clean run.

    The wait must stay bounded, but generous enough that a normal analysis
    is not reported as a failure.
    """
    ns = gate._parse_args(["--sha", "x"])
    assert ns.timeout >= 2700


def test_job_timeout_outlasts_the_script_timeout():
    """A job killed by Actions surfaces as infra noise, not a red gate."""
    import re
    wf = (Path(__file__).resolve().parents[1]
          / ".github" / "workflows" / "codeql-required.yml").read_text(encoding="utf-8")
    m = re.search(r"timeout-minutes:\s*(\d+)", wf)
    assert m, "codeql-required.yml must set an explicit job timeout"
    gate = _load()
    assert int(m.group(1)) * 60 > gate._parse_args(["--sha", "x"]).timeout
