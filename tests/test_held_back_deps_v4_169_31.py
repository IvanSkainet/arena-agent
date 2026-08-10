"""v4.169.31 -- a documented refusal that the bot proposing the bump could not read.

`requirements-mutation.in` had carried this since the sweep was built:

    # mutmut 2.5.1, NOT 3.x: 3.x copies the source tree into mutants/ and
    # breaks this project's imports. Measured, not assumed.

Dependabot opened PR #5 proposing `mutmut 3.7.0`. The reason was
documented, reviewed, and completely inert: it lives in a comment, and
the bot reads `.github/dependabot.yml`.

Worse than a wasted review. The mutation sweep is `workflow_dispatch`
only, so no pull-request check runs mutmut at all -- the bump would have
merged green and broken the sweep silently, discoverable only weeks
later by hand, when the change already looks like reviewed history.

Verified rather than trusted: mutmut 3.7.0's CLI aborts before it parses
arguments (`mutmut --version` raises FileNotFoundError out of
`_guess_source_paths`), so every invocation `scripts/mutation_sweep.py`
makes fails outright.

The guard also caught a false green in itself while being written: an
earlier draft searched the whole `.in` file for the rationale keyword, so
`websockets` passed on the strength of an unrelated note about
`async-timeout <3.11` several lines above. Only the comment block
directly above the pin counts now, and a test below holds that line.
"""
from __future__ import annotations

import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
GUARD = REPO_ROOT / "scripts" / "held_back_deps_ratchet.py"
DEPENDABOT = REPO_ROOT / ".github" / "dependabot.yml"


def run_guard(cwd: Path) -> subprocess.CompletedProcess[str]:
    """Run the guard that lives inside `cwd`, not the original."""
    return subprocess.run(
        [sys.executable, str(cwd / "scripts" / GUARD.name)],
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=120,
    )


@pytest.fixture
def repo_copy(tmp_path: Path) -> Path:
    work = tmp_path / "repo"
    (work / "scripts").mkdir(parents=True)
    (work / ".github").mkdir(parents=True)
    shutil.copy2(GUARD, work / "scripts" / GUARD.name)
    shutil.copy2(DEPENDABOT, work / ".github" / "dependabot.yml")
    for path in REPO_ROOT.glob("requirements-*.in"):
        shutil.copy2(path, work / path.name)
    return work


# ------------------------------------------------------- the pins themselves

def test_mutmut_is_still_on_2_x() -> None:
    """The bump PR #5 proposed must not be in the tree."""
    text = (REPO_ROOT / "requirements-mutation.in").read_text(encoding="utf-8")
    match = re.search(r"^mutmut==(?P<v>[^\s;#]+)", text, re.M)
    assert match, "no mutmut pin found — update this test with the guard"
    major = int(match.group("v").split(".")[0])
    assert major < 3, (
        f"mutmut is pinned at {match.group('v')}; 3.x copies the tree into "
        f"mutants/ and its CLI aborts before parsing arguments"
    )


def test_websockets_is_still_on_16_x() -> None:
    """17.0 requires Python >= 3.11; the package promises 3.10."""
    text = (REPO_ROOT / "requirements-ci.in").read_text(encoding="utf-8")
    match = re.search(r"^websockets==(?P<v>[^\s;#]+)", text, re.M)
    assert match
    assert int(match.group("v").split(".")[0]) < 17


def test_package_still_promises_python_310() -> None:
    """If this floor ever rises, the websockets hold can be reconsidered."""
    pyproject = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert 'requires-python = ">=3.10"' in pyproject, (
        "requires-python changed — revisit the websockets hold in "
        "scripts/held_back_deps_ratchet.py rather than leaving it stale"
    )


# ------------------------------------------------------- enforcement wiring

def test_dependabot_ignores_every_hold() -> None:
    text = DEPENDABOT.read_text(encoding="utf-8")
    for name in ("mutmut", "websockets"):
        assert name in text, (
            f"{name} is held back but dependabot.yml does not ignore it, so "
            f"the bot will propose the bump again"
        )


def test_guard_passes_on_the_real_tree() -> None:
    result = run_guard(REPO_ROOT)
    assert result.returncode == 0, f"guard red on a clean tree:\n{result.stderr}"


def test_guard_runs_in_ci() -> None:
    ci = (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert "held_back_deps_ratchet.py" in ci


def test_guard_runs_in_preflight() -> None:
    text = (REPO_ROOT / "scripts" / "preflight.py").read_text(encoding="utf-8")
    assert "held_back_deps_ratchet.py" in text


# -------------------------------------------------------------- sabotage

def test_guard_catches_the_exact_bump_from_pr_5(repo_copy: Path) -> None:
    target = repo_copy / "requirements-mutation.in"
    text = target.read_text(encoding="utf-8")
    sabotaged = re.sub(r"^mutmut==.*$", "mutmut==3.7.0", text, count=1, flags=re.M)
    assert sabotaged != text, "sabotage did not apply — the test proves nothing"
    target.write_text(sabotaged, encoding="utf-8")

    result = run_guard(repo_copy)
    assert result.returncode == 1, "the guard let PR #5 through"
    assert "mutmut" in result.stderr


def test_guard_catches_a_removed_dependabot_ignore(repo_copy: Path) -> None:
    """The half that actually stops the bot must not be quietly deleted."""
    target = repo_copy / ".github" / "dependabot.yml"
    text = target.read_text(encoding="utf-8")
    sabotaged = re.sub(
        r'      - dependency-name: "mutmut".*?versions: \[">=3\.0"\]\n',
        "",
        text,
        flags=re.S,
    )
    assert sabotaged != text, "sabotage did not apply"
    target.write_text(sabotaged, encoding="utf-8")

    result = run_guard(repo_copy)
    assert result.returncode == 1
    assert "dependabot" in result.stderr.lower()


def test_guard_catches_a_hand_rolled_websockets_bump(repo_copy: Path) -> None:
    target = repo_copy / "requirements-ci.in"
    text = target.read_text(encoding="utf-8")
    sabotaged = re.sub(
        r"^websockets==.*$", "websockets==17.0.1", text, count=1, flags=re.M
    )
    assert sabotaged != text
    target.write_text(sabotaged, encoding="utf-8")

    result = run_guard(repo_copy)
    assert result.returncode == 1
    assert "websockets" in result.stderr


def test_guard_catches_a_hold_that_lost_its_explanation(repo_copy: Path) -> None:
    """A ceiling nobody can justify gets raised by the next reader."""
    target = repo_copy / "requirements-mutation.in"
    lines = target.read_text(encoding="utf-8").splitlines()
    kept = [ln for ln in lines if not ln.lstrip().startswith("#")]
    target.write_text("\n".join(kept) + "\n", encoding="utf-8")

    result = run_guard(repo_copy)
    assert result.returncode == 1
    assert "explain" in result.stderr.lower()


def test_rationale_must_sit_directly_above_the_pin(repo_copy: Path) -> None:
    """The false green this guard shipped with, held down by a test.

    An unrelated comment elsewhere in the file must not satisfy the
    rationale requirement.
    """
    target = repo_copy / "requirements-ci.in"
    text = target.read_text(encoding="utf-8")
    stripped = re.sub(
        r"# websockets 16\.x.*?\n(?=websockets==)", "", text, flags=re.S
    )
    assert stripped != text, "the websockets note is not where this test expects"
    # The file still mentions 3.11 elsewhere (the async-timeout note), which
    # is exactly what fooled the first draft.
    assert "3.11" in stripped
    target.write_text(stripped, encoding="utf-8")

    result = run_guard(repo_copy)
    assert result.returncode == 1, (
        "an unrelated '3.11' elsewhere in the file satisfied the rationale "
        "check — the guard is reading the wrong lines again"
    )


def test_guard_fails_loudly_without_a_dependabot_config(tmp_path: Path) -> None:
    """No config must mean 'cannot verify', never 'fine'."""
    work = tmp_path / "bare"
    (work / "scripts").mkdir(parents=True)
    shutil.copy2(GUARD, work / "scripts" / GUARD.name)
    for path in REPO_ROOT.glob("requirements-*.in"):
        shutil.copy2(path, work / path.name)

    result = run_guard(work)
    assert result.returncode == 2, (
        "the guard reported success with no dependabot.yml to check against"
    )
