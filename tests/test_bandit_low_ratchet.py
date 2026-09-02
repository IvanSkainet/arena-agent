"""The bandit LOW ratchet must be a ratchet, not decoration.

Bandit was gating on HIGH+MEDIUM only. Measured on master f571d352 that meant
0 findings gated and 630 LOW findings ignored -- 263 of them B110
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
GATE = ROOT / "scripts" / "bandit_gate.py"
CEILING_FILE = ROOT / "docs" / "bandit-low-ceiling.txt"


def _load():
    spec = importlib.util.spec_from_file_location("bandit_gate", GATE)
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


def test_cli_still_exposes_check_bandit():
    """The split must not break `python scripts/security_gate.py bandit ...`."""
    cli = ROOT / "scripts" / "security_gate.py"
    spec = importlib.util.spec_from_file_location("security_gate_cli", cli)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert callable(mod.check_bandit)


def _ceilings(root=None):
    """Per-test ceilings, loaded the same way the gate loads them."""
    spec = importlib.util.spec_from_file_location(
        "bandit_per_test", ROOT / "scripts" / "bandit_per_test.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.per_test_ceilings(root or ROOT)


def _mixed_report(tmp_path, counts: dict[str, int]):
    results = []
    for tid, n in counts.items():
        for _ in range(n):
            results.append(_finding("LOW", tid))
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
    """A report matching every per-test ceiling exactly must pass.

    Uses the real per-test mix rather than N copies of one test id: since
    per-test ceilings landed, 496 B110 findings are correctly a failure even
    though the total is at the cap.
    """
    assert gate.check_bandit(_mixed_report(tmp_path, _ceilings())) == 0


def test_one_over_the_ceiling_is_red(gate, tmp_path):
    ceiling = gate._bandit_low_ceiling()
    assert gate.check_bandit(_report(tmp_path, low=ceiling + 1)) == 1


def test_below_the_ceiling_is_green(gate, tmp_path):
    counts = dict(_ceilings())
    counts["B110"] = max(counts["B110"] - 50, 0)
    assert gate.check_bandit(_mixed_report(tmp_path, counts)) == 0


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
    # 630 = 490 (arena/) + 119 (scripts/ + bin/) + 20 (skills/), measured
    # on the commit that widened the scan in #242. The rule is unchanged -- the ceiling
    # may only fall for a *fixed* scope. This number moved because the
    # gate started looking at three trees make_release_zip.py ships and
    # bandit had never scanned, where it found 7 HIGH and 22 MEDIUM.
    #
    # Raising a ceiling to accommodate new debt is still forbidden; the
    # written justification this assertion demands is the paragraph above
    # plus scripts/../tests/test_bandit_scope_matches_release.py, which
    # pins the scan to the shipped trees so the count cannot be lowered
    # again by quietly scanning less.
    assert gate._bandit_low_ceiling() <= 630, (
        "the LOW ceiling may only be lowered; raising it needs a written "
        "justification in the PR that raises it"
    )


def test_broken_ceiling_beats_high_findings(gate, tmp_path, monkeypatch):
    """A broken gate must report rc=2 even when findings would give rc=1.

    Regression: the ceiling was loaded after the HIGH/MEDIUM early return, so a
    missing baseline was masked as an ordinary failure and the "this gate
    cannot evaluate itself" signal was lost.
    """
    monkeypatch.setattr(gate, "ROOT", tmp_path / "empty-root")
    with pytest.raises(SystemExit) as exc:
        gate.check_bandit(_report(tmp_path, low=0, high=1))
    assert exc.value.code == 2


# --- per-test-id ceilings -------------------------------------------------
#
# The single total was gameable: swap 30 B404 findings for 30 new B110 ones
# and the total is unchanged, so the gate stayed green while the fail-open
# shape this repo actually cares about got worse.

CEILINGS_FILE = ROOT / "docs" / "bandit-low-ceilings.json"


def test_per_test_ceilings_file_is_committed():
    assert CEILINGS_FILE.is_file(), (
        f"{CEILINGS_FILE} must exist; without it the per-test ratchet has no baseline"
    )


def test_per_test_ceilings_sum_to_the_total_ceiling(gate):
    """The two baselines must agree, or one of them is silently dead."""
    per_test = sum(_ceilings().values())
    assert per_test == gate._bandit_low_ceiling(), (
        f"per-test ceilings sum to {per_test} but the total ceiling is "
        f"{gate._bandit_low_ceiling()}"
    )


def test_swapping_one_test_for_another_is_red(gate, tmp_path):
    """The regression that motivated this: same total, worse B110."""
    ceilings = _ceilings()
    counts = dict(ceilings)
    counts["B404"] -= 30
    counts["B110"] += 30
    assert sum(counts.values()) == sum(ceilings.values())  # total unchanged
    assert gate.check_bandit(_mixed_report(tmp_path, counts)) == 1


def test_each_test_at_its_ceiling_is_green(gate, tmp_path):
    assert gate.check_bandit(_mixed_report(tmp_path, _ceilings())) == 0


def test_lowering_one_test_is_green(gate, tmp_path):
    counts = dict(_ceilings())
    counts["B110"] = 0
    assert gate.check_bandit(_mixed_report(tmp_path, counts)) == 0


def test_missing_per_test_file_fails_closed(tmp_path):
    """No baseline means the gate cannot know: rc=2, never a silent pass."""
    with pytest.raises(SystemExit) as exc:
        _ceilings(tmp_path / "nope")
    assert exc.value.code == 2


@pytest.mark.parametrize("body", ["{oops", "[1, 2]", '"a string"'])
def test_unusable_per_test_file_fails_closed(tmp_path, body):
    """Malformed JSON *and* valid-but-wrong-shape JSON must both be rc=2."""
    root = tmp_path / "root"
    (root / "docs").mkdir(parents=True)
    (root / "docs" / "bandit-low-ceilings.json").write_text(body, encoding="utf-8")
    with pytest.raises(SystemExit) as exc:
        _ceilings(root)
    assert exc.value.code == 2


def test_b110_ceiling_may_only_fall(gate):
    """B110 is the fail-open shape; pin it so a PR cannot quietly raise it.

    250 -> 263 when the scan widened to scripts/ and bin/ (#242). The 19
    added sites were already in the shipped code; bandit simply had not
    been pointed at them. Nothing here relaxes the rule for arena/, which
    still contributes 244 of the 263.
    """
    assert _ceilings()["B110"] <= 263
