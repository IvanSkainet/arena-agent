"""Bandit must scan the Python trees the release actually ships.

#242: the job was named "bandit (must be 0 HIGH / 0 MEDIUM)" and passed,
while scanning only `arena/`. `scripts/` and `bin/` ship in the release
zip and contained 6 HIGH and 21 MEDIUM findings the gate had never seen.

Sabotage found the follow-on hole. Narrowing the scan back to `arena/`
does not fail anything: the LOW count simply drops, the ratchet reports
an "improvement", and the suggested next step is to lower the ceiling --
which would lock the blind spot in as the new normal. A shrinking number
looks like progress, so nothing in the ratchet can distinguish "we fixed
things" from "we stopped looking".

These tests pin the scope itself.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "security-scan.yml"

# The Python trees shipped by scripts/make_release_zip.py. Kept explicit
# rather than derived: deriving it from the same source the gate reads
# would make both wrong together.
SHIPPED_PYTHON_TREES = ("arena", "scripts", "bin")


def _bandit_command() -> str:
    """The `bandit -r ...` line from the security-scan workflow."""
    doc = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    for job in (doc.get("jobs") or {}).values():
        for step in (job.get("steps") or []):
            run = str(step.get("run", ""))
            if "bandit -r" in run:
                return run
    raise AssertionError("no `bandit -r` invocation found in security-scan.yml")


def _scanned_targets(command: str) -> set[str]:
    match = re.search(r"bandit -r ([^\n|]+?)(?:--|\n|$)", command)
    assert match, f"could not parse bandit targets from: {command!r}"
    return {t.strip().rstrip("/") for t in match.group(1).split() if t.strip()}


def test_bandit_scans_every_shipped_python_tree():
    """The gate's promise is only as wide as its scan."""
    scanned = _scanned_targets(_bandit_command())
    missing = sorted(set(SHIPPED_PYTHON_TREES) - scanned)
    assert not missing, (
        f"bandit does not scan {missing}, but make_release_zip.py ships "
        f"them. A gate advertising '0 HIGH / 0 MEDIUM' must look at "
        f"everything that reaches a user."
    )


def test_the_shipped_trees_exist_and_contain_python():
    """A tree that vanished would make the check above vacuous."""
    for tree in SHIPPED_PYTHON_TREES:
        path = REPO_ROOT / tree
        assert path.is_dir(), f"{tree}/ is missing; update SHIPPED_PYTHON_TREES"
        assert any(path.rglob("*.py")), f"{tree}/ contains no Python to scan"


def test_the_scope_gate_rejects_a_narrowed_scan():
    """Negative test: this is the mutation sabotage found.

    Driven with synthetic prose rather than the real workflow, so it
    fails when the *check* breaks rather than only when the workflow is
    already wrong.
    """
    narrowed = _scanned_targets("bandit -r arena/ --skip B101 -f json")
    assert sorted(set(SHIPPED_PYTHON_TREES) - narrowed) == ["bin", "scripts"]


def test_the_scope_gate_accepts_the_full_scan():
    """And must not cry wolf on a correct invocation."""
    full = _scanned_targets("bandit -r arena/ scripts/ bin/ --skip B101 -f json")
    assert not set(SHIPPED_PYTHON_TREES) - full


@pytest.mark.parametrize("ceiling_file", [
    "docs/bandit-low-ceiling.txt",
    "docs/bandit-low-ceilings.json",
])
def test_ceiling_files_exist(ceiling_file):
    """Both ratchets fail closed without these; keep them discoverable."""
    assert (REPO_ROOT / ceiling_file).is_file(), f"{ceiling_file} is missing"


def test_total_ceiling_matches_the_sum_of_per_test_ceilings():
    """The docs say they must agree; a drift makes one of them a lie."""
    import json

    total_text = (REPO_ROOT / "docs" / "bandit-low-ceiling.txt").read_text(
        encoding="utf-8")
    total = int(total_text.split("#")[0].strip())
    per_test = json.loads(
        (REPO_ROOT / "docs" / "bandit-low-ceilings.json").read_text(
            encoding="utf-8"))
    summed = sum(v for k, v in per_test.items() if not k.startswith("_"))
    assert total == summed, (
        f"docs/bandit-low-ceiling.txt says {total} but the per-test "
        f"ceilings sum to {summed}"
    )
