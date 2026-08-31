"""The poutine ratchet must fail closed, like the bandit and CodeQL gates.

poutine is a second workflow scanner alongside zizmor, which matters because
the two disagree: zizmor exempts GitHub-owned actions from its pinning rules,
so running it alone leaves a blind spot. Measured on master 16091e32 poutine
reports 8 findings that zizmor does not surface.

These tests pin the ratchet's contract: rising is red, falling is green, and a
gate that cannot find or parse its own inputs exits 2 rather than passing.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
GATE = ROOT / ".github" / "scripts" / "poutine_gate.py"
CEILING = ROOT / "docs" / "poutine-ceiling.txt"


def _load():
    spec = importlib.util.spec_from_file_location("poutine_gate", GATE)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def gate():
    return _load()


def _report(tmp_path, n, rule="github_action_from_unverified_creator_used"):
    findings = [
        {"rule_id": rule,
         "meta": {"path": ".github/workflows/ci.yml", "line": 1, "job": "x"}}
        for _ in range(n)
    ]
    p = tmp_path / "poutine.json"
    p.write_text(json.dumps({"findings": findings}), encoding="utf-8")
    return str(p)


def test_gate_script_is_committed():
    assert GATE.is_file(), f"{GATE} is missing"


def test_ceiling_file_is_committed():
    assert CEILING.is_file(), f"{CEILING} is missing; the ratchet has no baseline"


def test_at_the_ceiling_is_green(gate, tmp_path):
    assert gate.main(["--report", _report(tmp_path, gate._ceiling())]) == 0


def test_one_over_the_ceiling_is_red(gate, tmp_path):
    assert gate.main(["--report", _report(tmp_path, gate._ceiling() + 1)]) == 1


def test_below_the_ceiling_is_green(gate, tmp_path):
    assert gate.main(["--report", _report(tmp_path, 0)]) == 0


def test_missing_report_fails_closed(gate, tmp_path):
    with pytest.raises(SystemExit) as exc:
        gate.main(["--report", str(tmp_path / "absent.json")])
    assert exc.value.code == 2


def test_malformed_report_fails_closed(gate, tmp_path):
    p = tmp_path / "bad.json"
    p.write_text("{not json", encoding="utf-8")
    with pytest.raises(SystemExit) as exc:
        gate.main(["--report", str(p)])
    assert exc.value.code == 2


def test_report_without_findings_array_fails_closed(gate, tmp_path):
    p = tmp_path / "odd.json"
    p.write_text(json.dumps({"packages": []}), encoding="utf-8")
    with pytest.raises(SystemExit) as exc:
        gate.main(["--report", str(p)])
    assert exc.value.code == 2


def test_missing_ceiling_fails_closed(gate, tmp_path, monkeypatch):
    report = _report(tmp_path, 1)
    monkeypatch.setattr(gate, "CEILING_FILE", tmp_path / "absent.txt")
    with pytest.raises(SystemExit) as exc:
        gate.main(["--report", report])
    assert exc.value.code == 2


def test_malformed_ceiling_fails_closed(gate, tmp_path, monkeypatch):
    bad = tmp_path / "ceiling.txt"
    bad.write_text("eight\n", encoding="utf-8")
    report = _report(tmp_path, 1)
    monkeypatch.setattr(gate, "CEILING_FILE", bad)
    with pytest.raises(SystemExit) as exc:
        gate.main(["--report", report])
    assert exc.value.code == 2


def test_ceiling_may_not_drift_upward(gate):
    """A ceiling nobody lowers becomes a licence to add findings."""
    assert gate._ceiling() <= 8, (
        "the poutine ceiling may only be lowered; raising it needs a written "
        "justification in the PR that raises it"
    )
