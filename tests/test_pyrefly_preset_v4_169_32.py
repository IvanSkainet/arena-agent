"""v4.169.32 -- mypy was installed by every CI job and executed by none.

Dependabot proposed bumping mypy 1.19.1 to 2.3.0, twice: inside a group
(PR #5) and again on its own the moment that was closed (PR #6). Chasing
the second one down turned up why the bump was empty -- mypy never runs
here. Type checking is pyrefly's, gated by `scripts/quality_ratchet.py`.
The only references in the tree were a config section, two comments and a
cache-directory exclusion.

The obvious follow-up is the trap this module guards. `[tool.mypy]` looks
like leftover configuration for the tool just deleted. It is pyrefly's:
pyrefly has no config of its own here, imports that section, and the mere
PRESENCE of it selects the `legacy` preset. Measured on this tree:

    with    [tool.mypy]:  preset legacy, 0 errors
    without [tool.mypy]:  preset basic, quality ratchet fails, +11 findings

`basic` reports fewer errors while checking less -- it drops call and
assignment checks. A green that means less than the red it replaced.

The guard shipped with a hole of its own, found by sabotage rather than
by reading it: adding a `pyrefly.toml` made pyrefly stop printing the
preset line at all, so "could not measure" was reported as a SKIP and the
run passed with the preset silently changed. Absence of evidence read as
evidence. A `pyrefly.toml` appearing is now a failure in itself, and the
test for that is below.
"""
from __future__ import annotations

import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
GUARD = REPO_ROOT / "scripts" / "pyrefly_preset_ratchet.py"
PYPROJECT = REPO_ROOT / "pyproject.toml"


def run_guard(cwd: Path) -> subprocess.CompletedProcess[str]:
    """Run the copy of the guard inside `cwd`, never the original."""
    return subprocess.run(
        [sys.executable, str(cwd / "scripts" / GUARD.name)],
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=900,
    )


def strip_mypy_section(text: str) -> str:
    text = re.sub(r"\n\[tool\.mypy\]\n.*?(?=\n\[)", "\n", text, flags=re.S)
    return re.sub(
        r"\n\[\[tool\.mypy\.overrides\]\]\n.*?(?=\n\[)", "\n", text, flags=re.S
    )


@pytest.fixture
def repo_copy(tmp_path: Path) -> Path:
    """Enough of the tree for the guard to run: config plus a package."""
    work = tmp_path / "repo"
    (work / "scripts").mkdir(parents=True)
    shutil.copy2(GUARD, work / "scripts" / GUARD.name)
    shutil.copy2(PYPROJECT, work / "pyproject.toml")
    (work / "arena").mkdir()
    (work / "arena" / "__init__.py").write_text("", encoding="utf-8")
    (work / "arena" / "sample.py").write_text(
        "def add(a: int, b: int) -> int:\n    return a + b\n", encoding="utf-8"
    )
    return work


# ------------------------------------------------------------ the removal

def test_mypy_package_is_gone_from_the_ci_pins() -> None:
    text = (REPO_ROOT / "requirements-ci.in").read_text(encoding="utf-8")
    assert not re.search(r"^mypy==", text, re.M), (
        "mypy is pinned again; it is installed by every job and executed by "
        "none. If something now runs it, wire that up explicitly."
    )


def test_mypy_is_gone_from_the_ci_lock() -> None:
    text = (REPO_ROOT / "requirements-ci.lock").read_text(encoding="utf-8")
    assert not re.search(r"^mypy==", text, re.M)


def test_nothing_in_the_tree_actually_invokes_mypy() -> None:
    """If this ever fails, mypy earned its place back -- pin it deliberately."""
    hits: list[str] = []
    patterns = (
        re.compile(r"-m\s+mypy\b"),
        re.compile(r"^\s*(run:|\$)?\s*mypy\s+(--|check|arena|scripts)", re.M),
    )
    for path in REPO_ROOT.rglob("*"):
        if not path.is_file() or ".git" in path.parts:
            continue
        if path.suffix not in {".py", ".yml", ".yaml", ".sh", ".cfg", ".toml"}:
            continue
        if path.name.startswith("requirements-"):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        if any(p.search(text) for p in patterns):
            hits.append(str(path.relative_to(REPO_ROOT)))
    assert not hits, f"something invokes mypy after all: {hits}"


# --------------------------------------------------------- the load-bearing bit

def test_tool_mypy_section_survives() -> None:
    """It is pyrefly's config, not leftovers from the removed package."""
    text = PYPROJECT.read_text(encoding="utf-8")
    assert re.search(r"^\[tool\.mypy\]\s*$", text, re.M), (
        "[tool.mypy] was deleted. pyrefly imports it, and its presence "
        "selects the `legacy` preset; without it pyrefly drops to `basic` "
        "and stops checking calls and assignments."
    )


def test_the_section_explains_that_it_is_not_dead() -> None:
    """The next person to tidy up must hit the reason before the delete key."""
    text = PYPROJECT.read_text(encoding="utf-8")
    head = text[: text.index("[tool.mypy]")]
    tail = head[-1400:]
    assert "pyrefly" in tail.lower(), (
        "nothing above [tool.mypy] says the section belongs to pyrefly"
    )


def test_no_pyrefly_toml_shadowing_the_import() -> None:
    assert not (REPO_ROOT / "pyrefly.toml").exists(), (
        "a pyrefly.toml overrides the [tool.mypy] import and hides which "
        "preset is in force"
    )


# --------------------------------------------------------------- the guard

def test_guard_passes_on_the_real_tree() -> None:
    result = run_guard(REPO_ROOT)
    assert result.returncode == 0, f"guard red on a clean tree:\n{result.stderr}"


def test_guard_catches_a_deleted_mypy_section(repo_copy: Path) -> None:
    target = repo_copy / "pyproject.toml"
    text = target.read_text(encoding="utf-8")
    sabotaged = strip_mypy_section(text)
    # Assert on the SECTION HEADER, not on the string appearing anywhere:
    # the prose above the section mentions `[tool.mypy]` by name, and an
    # earlier version of this assertion failed on its own explanation.
    assert not re.search(r"^\[tool\.mypy\]\s*$", sabotaged, re.M), (
        "sabotage did not apply — the test proves nothing"
    )
    target.write_text(sabotaged, encoding="utf-8")

    result = run_guard(repo_copy)
    assert result.returncode == 1, (
        "the guard allowed the section to be tidied away"
    )
    assert "tool.mypy" in result.stderr


def test_guard_catches_a_pyrefly_toml_appearing(repo_copy: Path) -> None:
    """The hole the first draft had: unmeasurable must not mean fine."""
    (repo_copy / "pyrefly.toml").write_text('preset = "basic"\n', encoding="utf-8")

    result = run_guard(repo_copy)
    assert result.returncode == 1, (
        "a pyrefly.toml silently took over the preset and the guard passed "
        "because it could no longer see which preset was chosen"
    )
    assert "pyrefly.toml" in result.stderr


def test_guard_passes_on_an_honest_copy(repo_copy: Path) -> None:
    """Reverse sabotage: an untouched tree must stay green."""
    result = run_guard(repo_copy)
    assert result.returncode == 0, (
        f"false positive on an unmodified copy:\n{result.stderr}"
    )


def test_guard_never_reports_ok_without_the_section(tmp_path: Path) -> None:
    """Fail closed with no pyproject.toml at all."""
    work = tmp_path / "bare"
    (work / "scripts").mkdir(parents=True)
    shutil.copy2(GUARD, work / "scripts" / GUARD.name)

    result = run_guard(work)
    assert result.returncode == 1


# --------------------------------------------------------------- the wiring

def test_guard_runs_in_ci() -> None:
    ci = (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert "pyrefly_preset_ratchet.py" in ci


def test_guard_runs_in_preflight() -> None:
    text = (REPO_ROOT / "scripts" / "preflight.py").read_text(encoding="utf-8")
    assert "pyrefly_preset_ratchet.py" in text


def test_dependabot_will_not_propose_mypy_again() -> None:
    """PR #5 proposed it in a group; PR #6 proposed it again alone."""
    text = (REPO_ROOT / ".github" / "dependabot.yml").read_text(encoding="utf-8")
    assert re.search(r'dependency-name:\s*"mypy"', text), (
        "nothing stops Dependabot opening a third mypy PR"
    )
