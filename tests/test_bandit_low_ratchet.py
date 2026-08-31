"""The bandit LOW ratchet must be a ratchet, not decoration.

Bandit was gating on HIGH+MEDIUM only. Measured on master f571d352 that meant
0 findings gated and 496 LOW findings ignored -- 250 of them B110
try_except_pass, the silently-swallowed-exception shape this repo keeps
fighting. The ratchet caps LOW at a committed ceiling.

These tests pin the properties that make it worth having: it goes red when the
count rises, it stays green when the count falls, and -- the important one --
it fails *closed* when its own baseline file is missing, instead of waving the
scan through the way `coverage_diff` used to.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
GATE = ROOT / "scripts" / "security_gate.py"
CEILING_FILE = ROOT / "docs" / "bandit-low-ceiling.txt"


def _load():
    spec = importlib.util.spec_from_file_location("security_gate", GATE)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture()
def gate():
    return _load()


def _finding(severity="LOW", test_id="B110"):
    return {
        "issue_severity": severity,
        "issue_confidence": "HIGH",
        "test_id": test_id,
        "issue_text": "Try, Except, Pass detected.",
        "filename": "arena/example.py",
        "line_number": 1,
    }


def _report(tmp_path, *, low=0, medium=0, high=0):
    results = (
        [_finding("LOW") for _ in range(low)]
        + [_finding("MEDIUM") for _ in range(medium)]
        + [_finding("HIGH") for _ in range(high)]
    )
    path = tmp_path / "bandit.json"
    path.write_text(json.dumps({"results": results}), encoding="utf-8")
    return str(path)


def test_ceiling_file_is_committed():
    assert CEILING_FILE.is_file(), (
        f"{CEILING_FILE} must exist; without it the LOW ratchet has no baseline"
    )


def test_ceiling_file_parses_to_an_int(gate):
    assert gate._bandit_low_ceiling() > 0


def test_at_the_ceiling_is_green(gate, tmp_path):
    ceiling = gate._bandit_low_ceiling()
    assert gate.check_bandit(_report(tmp_path, low=ceiling)) == 0


def test_one_over_the_ceiling_is_red(gate, tmp_path):
    ceiling = gate._bandit_low_ceiling()
    assert gate.check_bandit(_report(tmp_path, low=ceiling + 1)) == 1


def test_below_the_ceiling_is_green(gate, tmp_path):
    ceiling = gate._bandit_low_ceiling()
    assert gate.check_bandit(_report(tmp_path, low=max(ceiling - 50, 0))) == 0


def test_high_still_fails_regardless_of_low(gate, tmp_path):
    assert gate.check_bandit(_report(tmp_path, low=0, high=1)) == 1


def test_medium_still_fails_regardless_of_low(gate, tmp_path):
    assert gate.check_bandit(_report(tmp_path, low=0, medium=1)) == 1


def test_missing_ceiling_file_fails_closed(gate, tmp_path, monkeypatch):
    """The regression that matters: no baseline must not mean 'pass'."""
    monkeypatch.setattr(gate, "ROOT", tmp_path / "empty-root")
    with pytest.raises(SystemExit) as exc:
        gate.check_bandit(_report(tmp_path, low=1))
    assert exc.value.code == 2


def test_malformed_ceiling_file_fails_closed(gate, tmp_path, monkeypatch):
    root = tmp_path / "root"
    (root / "docs").mkdir(parents=True)
    (root / "docs" / "bandit-low-ceiling.txt").write_text("not-a-number\n", encoding="utf-8")
    monkeypatch.setattr(gate, "ROOT", root)
    with pytest.raises(SystemExit) as exc:
        gate.check_bandit(_report(tmp_path, low=1))
    assert exc.value.code == 2


def test_ceiling_matches_reality_on_this_tree(gate):
    """Guard against the ceiling drifting far above the real count.

    A ceiling nobody lowers becomes a licence to add findings. This does not
    re-run bandit (too slow for the unit suite); it just refuses an absurd
    ceiling that would neuter the gate.
    """
    assert gate._bandit_low_ceiling() <= 496, (
        "the LOW ceiling may only be lowered; raising it needs a written "
        "justification in the PR that raises it"
    )
