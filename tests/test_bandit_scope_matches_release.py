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

import importlib.util
import re
import subprocess
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "security-scan.yml"

def _shipped_python_trees() -> set[str]:
    """Top-level trees containing Python that the release actually ships.

    Derived from `make_release_zip.should_exclude`, not hand-listed.
    Review on #244 was right that a second manual list drifts: mine said
    `arena, scripts, bin`, and asking the release script turned up
    `skills/` too -- 20 LOW and 1 MEDIUM that nothing had ever scanned.

    This is not circular. The release script decides what ships; the
    workflow decides what is scanned; this compares the two. Both would
    have to break in the same direction for the check to pass wrongly.
    """
    spec = importlib.util.spec_from_file_location(
        "make_release_zip", REPO_ROOT / "scripts" / "make_release_zip.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    tracked = subprocess.run(
        ["git", "ls-files"], cwd=REPO_ROOT,
        capture_output=True, text=True, check=True, timeout=120).stdout
    trees = set()
    for rel in tracked.splitlines():
        if not rel.endswith(".py") or "/" not in rel:
            continue
        if module.should_exclude(rel):
            continue
        trees.add(rel.split("/")[0])
    return trees


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
    """Trees bandit is pointed at, minus anything it is told to exclude.

    Subtracting the exclusions is not pedantry: `bandit -r arena/ scripts/
    bin/ --exclude bin/` names every shipped tree while scanning two of
    them. Parsing only the positional targets would call that compliant,
    which is the same "looks covered, isn't" failure as #242 itself.
    (Raised in review on #244.)
    """
    match = re.search(r"bandit -r ([^\n|]+?)(?:--|\n|$)", command)
    assert match, f"could not parse bandit targets from: {command!r}"
    targets = {t.strip().rstrip("/") for t in match.group(1).split() if t.strip()}
    return targets - _excluded_paths(command)


def _excluded_paths(command: str) -> set[str]:
    """Paths removed from the scan via --exclude / -x."""
    excluded: set[str] = set()
    for match in re.finditer(r"(?:--exclude|-x)[ =]([^\s\\]+)", command):
        for part in match.group(1).split(","):
            part = part.strip().rstrip("/").lstrip("./")
            if part:
                excluded.add(part)
    return excluded


def test_bandit_scans_every_shipped_python_tree():
    """The gate's promise is only as wide as its scan."""
    scanned = _scanned_targets(_bandit_command())
    missing = sorted(set(_shipped_python_trees()) - scanned)
    assert not missing, (
        f"bandit does not scan {missing}, but make_release_zip.py ships "
        f"them. A gate advertising '0 HIGH / 0 MEDIUM' must look at "
        f"everything that reaches a user."
    )


def test_the_shipped_trees_exist_and_contain_python():
    """A tree that vanished would make the check above vacuous."""
    for tree in _shipped_python_trees():
        path = REPO_ROOT / tree
        assert path.is_dir(), f"{tree}/ is missing; update _shipped_python_trees()"
        assert any(path.rglob("*.py")), f"{tree}/ contains no Python to scan"


def test_the_scope_gate_rejects_a_narrowed_scan():
    """Negative test: this is the mutation sabotage found.

    Driven with synthetic prose rather than the real workflow, so it
    fails when the *check* breaks rather than only when the workflow is
    already wrong.
    """
    narrowed = _scanned_targets("bandit -r arena/ --skip B101 -f json")
    missing = set(_shipped_python_trees()) - narrowed
    assert missing, "narrowing to arena/ must leave shipped trees unscanned"
    assert "arena" not in missing


def test_an_exclude_cannot_smuggle_a_shipped_tree_out_of_the_scan():
    """`--exclude bin/` must not read as "bin/ is scanned".

    Verified against the real behaviour: bandit supports --exclude, so a
    command naming all three trees can still skip one. Before this, the
    gate parsed positional targets only and passed such a command.
    """
    smuggled = _scanned_targets(
        "bandit -r arena/ scripts/ bin/ --exclude bin/ --skip B101")
    assert "bin" not in smuggled
    assert "bin" in set(_shipped_python_trees()) - smuggled


def test_exclude_parsing_handles_the_forms_bandit_accepts():
    """-x, --exclude, `=` form, and comma-separated lists."""
    for variant in ("-x bin/", "--exclude bin/", "--exclude=bin/",
                    "--exclude scripts/,bin/"):
        cmd = f"bandit -r arena/ scripts/ bin/ {variant} --skip B101"
        assert "bin" not in _scanned_targets(cmd), variant


def test_the_scope_gate_accepts_the_full_scan():
    """And must not cry wolf on a correct invocation."""
    trees = sorted(_shipped_python_trees())
    full = _scanned_targets(
        "bandit -r " + " ".join(f"{t}/" for t in trees) + " --skip B101 -f json")
    assert not set(trees) - full


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
