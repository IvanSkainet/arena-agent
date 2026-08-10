"""v4.169.30 -- the repository pinned two different versions of its linter.

`requirements-ci.in` pinned `ruff==0.16.1`; `requirements-lint.in` pinned
`ruff==0.16.2`. Both are installed by CI. The "Lint (ruff)" job installs
the lint lock and runs ruff directly; the "Debt totals" job installs the
CI lock and runs `scripts/lint_ratchet.py`, which invokes whichever ruff
is on PATH. So there were two linters of record, and the ratchet baseline
could only be correct for one of them. Nothing was red: every pin was
hash-locked, `check_lock_freshness.py` verified each `.in`/`.lock` pair
against itself, and no check compared the pairs to each other.

The second shape of the same defect: three jobs install two locks into
one interpreter (packaging-e2e, e2e-installed, mutation sweep). pip lets
the later install overwrite the earlier one, so a disagreement on a
shared transitive package silently replaces a hash-verified version with
a different hash-verified version. That pairing is conflict-free today,
which is the moment to pin it down rather than after it drifts.

These tests cover the fix (one ruff version) and the guard, including
the reverse direction: locks that disagree but never share an
interpreter must NOT be reported, because a guard that fires on
`requirements-security.lock` resolving `rich` its own way is a guard
someone will switch off.
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
GUARD = REPO_ROOT / "scripts" / "lock_conflict_ratchet.py"
WORKFLOWS = REPO_ROOT / ".github" / "workflows"

IN_PIN = re.compile(
    r"^(?P<name>[A-Za-z0-9][A-Za-z0-9._-]*)(\[[^\]]+\])?=="
    r"(?P<version>[^\s;#]+)",
    re.M,
)


def canonical(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def run_guard(cwd: Path) -> subprocess.CompletedProcess[str]:
    """Run the guard that lives inside `cwd`.

    The guard resolves the repository from its own location, not from the
    working directory, so a sabotage test must invoke the *copy* -- an
    earlier draft of this file ran the original and every sabotage case
    silently inspected the real, clean tree instead.
    """
    guard = cwd / "scripts" / GUARD.name
    return subprocess.run(
        [sys.executable, str(guard)],
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=120,
    )


@pytest.fixture
def repo_copy(tmp_path: Path) -> Path:
    """A minimal copy of the requirement/workflow surface the guard reads."""
    work = tmp_path / "repo"
    (work / "scripts").mkdir(parents=True)
    (work / ".github" / "workflows").mkdir(parents=True)
    (work / "scripts" / GUARD.name).write_bytes(GUARD.read_bytes())
    for path in REPO_ROOT.glob("requirements-*.in"):
        (work / path.name).write_bytes(path.read_bytes())
    for path in REPO_ROOT.glob("requirements-*.lock"):
        (work / path.name).write_bytes(path.read_bytes())
    for path in WORKFLOWS.glob("*.yml"):
        (work / ".github" / "workflows" / path.name).write_bytes(path.read_bytes())
    return work


# ---------------------------------------------------------------- the fix

def test_ruff_is_pinned_to_one_version_everywhere() -> None:
    """The actual bug: two .in files demanding different ruff releases."""
    found: dict[str, str] = {}
    for path in REPO_ROOT.glob("requirements-*.in"):
        for match in IN_PIN.finditer(path.read_text(encoding="utf-8")):
            if canonical(match.group("name")) == "ruff":
                found[path.name] = match.group("version")

    assert found, "no .in file pins ruff any more — update this test"
    assert len(set(found.values())) == 1, (
        f"ruff is pinned at conflicting versions: {found}. The lint job and "
        f"the debt-totals job would run different linters."
    )


def test_ci_lock_matches_the_declared_ruff() -> None:
    """The lock actually carries the version the .in demands."""
    declared = None
    for match in IN_PIN.finditer(
        (REPO_ROOT / "requirements-ci.in").read_text(encoding="utf-8")
    ):
        if canonical(match.group("name")) == "ruff":
            declared = match.group("version")
    assert declared is not None

    lock = (REPO_ROOT / "requirements-ci.lock").read_text(encoding="utf-8")
    assert re.search(rf"^ruff=={re.escape(declared)}\b", lock, re.M), (
        "requirements-ci.lock does not pin the ruff version its .in declares"
    )


# ------------------------------------------------------------- the guard

def test_guard_passes_on_the_real_tree() -> None:
    result = run_guard(REPO_ROOT)
    assert result.returncode == 0, (
        f"guard is red on a tree that should be clean:\n{result.stderr}"
    )


def test_guard_catches_conflicting_direct_pins(repo_copy: Path) -> None:
    """Sabotage: reintroduce the exact defect that was shipped."""
    target = repo_copy / "requirements-lint.in"
    text = target.read_text(encoding="utf-8")
    sabotaged = re.sub(r"^ruff==.*$", "ruff==0.15.0", text, count=1, flags=re.M)
    assert sabotaged != text, "sabotage did not apply — the test proves nothing"
    target.write_text(sabotaged, encoding="utf-8")

    result = run_guard(repo_copy)
    assert result.returncode == 1, "the guard did not notice two ruff versions"
    assert "ruff" in result.stderr


def test_guard_catches_conflict_between_co_installed_locks(repo_copy: Path) -> None:
    """Sabotage: two locks installed into one interpreter disagree."""
    target = repo_copy / "requirements-packaging.lock"
    text = target.read_text(encoding="utf-8")
    sabotaged = re.sub(
        r"^packaging==[^\s\\]+", "packaging==0.0.1", text, count=1, flags=re.M
    )
    assert sabotaged != text, "sabotage did not apply — the test proves nothing"
    target.write_text(sabotaged, encoding="utf-8")

    result = run_guard(repo_copy)
    assert result.returncode == 1, (
        "a job installs both locks into one environment; the guard missed the "
        "disagreement"
    )
    assert "packaging" in result.stderr


def test_guard_ignores_locks_that_never_share_an_interpreter(
    repo_copy: Path,
) -> None:
    """Reverse sabotage: a legitimately independent resolution is not a bug.

    requirements-security.lock resolves rich/packaging/cffi differently
    from requirements-ci.lock because its own graph demands it, and no job
    installs both. A detector that reports this is worse than no detector.
    """
    target = repo_copy / "requirements-security.lock"
    text = target.read_text(encoding="utf-8")
    sabotaged = re.sub(
        r"^rich==[^\s\\]+", "rich==1.0.0", text, count=1, flags=re.M
    )
    assert sabotaged != text
    target.write_text(sabotaged, encoding="utf-8")

    result = run_guard(repo_copy)
    assert result.returncode == 0, (
        f"false positive: locks that never meet were reported as conflicting:\n"
        f"{result.stderr}"
    )


def test_guard_accepts_a_new_job_pairing_consistent_locks(repo_copy: Path) -> None:
    """Reverse sabotage: an honest new job must stay green."""
    ci = repo_copy / ".github" / "workflows" / "ci.yml"
    ci.write_text(
        ci.read_text(encoding="utf-8")
        + "\n"
        "  honest-job:\n"
        "    name: Installs two locks that agree\n"
        "    runs-on: ubuntu-latest\n"
        "    steps:\n"
        "      - run: python -m pip install --require-hashes -r "
        "requirements-ci.lock\n"
        "      - run: python -m pip install --require-hashes -r "
        "requirements-mutation.lock\n",
        encoding="utf-8",
    )
    result = run_guard(repo_copy)
    assert result.returncode == 0, (
        f"honest job flagged as a conflict:\n{result.stderr}"
    )


def test_guard_discovers_new_jobs_rather_than_a_hardcoded_list(
    repo_copy: Path,
) -> None:
    """A future job combining locks must be covered without editing the guard."""
    ci = repo_copy / ".github" / "workflows" / "ci.yml"
    ci.write_text(
        ci.read_text(encoding="utf-8")
        + "\n"
        "  future-job:\n"
        "    name: Pairs locks that disagree\n"
        "    runs-on: ubuntu-latest\n"
        "    steps:\n"
        "      - run: python -m pip install --require-hashes -r "
        "requirements-ci.lock\n"
        "      - run: python -m pip install --require-hashes -r "
        "requirements-security.lock\n",
        encoding="utf-8",
    )
    result = run_guard(repo_copy)
    assert result.returncode == 1, (
        "the guard only knows the jobs that existed when it was written"
    )
    assert "future-job" in result.stderr


def test_guard_fails_loudly_when_it_finds_nothing(tmp_path: Path) -> None:
    """No inputs must mean 'broken', never 'clean' — fail closed."""
    empty = tmp_path / "empty"
    (empty / "scripts").mkdir(parents=True)
    (empty / "scripts" / GUARD.name).write_bytes(GUARD.read_bytes())

    result = run_guard(empty)
    assert result.returncode == 2, (
        "a guard that finds no requirement files reported success"
    )


# ------------------------------------------------------------ the wiring

def test_guard_runs_in_ci() -> None:
    ci = (WORKFLOWS / "ci.yml").read_text(encoding="utf-8")
    assert "lock_conflict_ratchet.py" in ci, (
        "the guard exists but no workflow runs it"
    )


def test_guard_runs_in_preflight() -> None:
    preflight = (REPO_ROOT / "scripts" / "preflight.py").read_text(encoding="utf-8")
    assert "lock_conflict_ratchet.py" in preflight, (
        "preflight does not run the guard, so a conflict reaches CI first"
    )
