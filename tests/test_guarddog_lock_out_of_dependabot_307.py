"""The GuardDog lock must stay outside the directory Dependabot watches.

Why this file exists
--------------------
`ci/guarddog/requirements.txt` is guarddog's own compiled dependency
closure, not a list of packages this project picked. While it lived in the
repository root as `requirements-guarddog.txt`, Dependabot's pip ecosystem
-- declared with `directory: "/"` -- treated it as an ordinary requirements
file and proposed bumps one package at a time. Two of guarddog 3.2.0's
transitive pins are exact ranges:

    tarsafe                   >=0.0.5,<0.0.6
    disposable-email-domains  >=0.0.237,<0.0.238

so each isolated bump made `pip install --require-hashes` die with
ResolutionImpossible *before* the scanner started. The required
"Malicious dependency scan (GuardDog)" check went red and no malware scan
ran at all -- twice inside a single pull request (#285, #307).

The first patch was per-name `ignore` entries in `.github/dependabot.yml`.
That does not scale: guarddog's transitive set changes with every release,
and each new name announces itself as another red required check on a
Monday morning. The structural fix is the one this file guards -- the lock
sits in a subdirectory Dependabot's pip ecosystem does not watch.

Restoring the old layout is a one-line move that looks like tidying and
breaks nothing visible until the next weekly bump, which is exactly the
kind of regression a gate is for.
"""

from __future__ import annotations

import fnmatch
import importlib.util
import pathlib

try:
    import yaml
except ImportError as exc:  # pragma: no cover - exercised only without PyYAML
    # A raise rather than a skip: a gate that evaporates when a dependency
    # is missing reports success precisely where nobody is watching.
    raise RuntimeError(
        "PyYAML is required for the guarddog lock placement gate; without it "
        "this test would skip and the audit would pass by default"
    ) from exc

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
LOCK = REPO_ROOT / "ci" / "guarddog" / "requirements.txt"
LOCK_IN = REPO_ROOT / "ci" / "guarddog" / "requirements.in"
OLD_LOCK = REPO_ROOT / "requirements-guarddog.txt"
DEPENDABOT = REPO_ROOT / ".github" / "dependabot.yml"
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "guarddog.yml"
RATCHET = REPO_ROOT / "scripts" / "pinned_pip_ratchet.py"
FRESHNESS = REPO_ROOT / "scripts" / "check_lock_freshness.py"
RELOCK = REPO_ROOT / ".github" / "workflows" / "relock-dependabot.yml"

# guarddog's own transitive pins. Neither is a dependency this project
# chose, and neither may come back as a Dependabot ignore entry: an ignore
# is where we record *our* decisions, and silently accumulating upstream's
# is how the root-directory layout hid its own cost.
UPSTREAM_PINS = ("tarsafe", "disposable-email-domains")


def _pip_ecosystem() -> dict:
    config = yaml.safe_load(DEPENDABOT.read_text(encoding="utf-8"))
    pip = [u for u in config["updates"] if u["package-ecosystem"] == "pip"]
    assert len(pip) == 1, (
        "expected exactly one pip ecosystem block in dependabot.yml; found "
        f"{len(pip)}. If a second one was added, this gate must learn which "
        "directories it watches before it can claim the lock is out of reach."
    )
    return pip[0]


def test_the_lock_lives_outside_the_watched_directory() -> None:
    assert LOCK.is_file(), (
        "ci/guarddog/requirements.txt is missing. The GuardDog job installs "
        "from it; without the file the required check cannot run."
    )
    assert not OLD_LOCK.exists(), (
        "requirements-guarddog.txt is back in the repository root. Dependabot's "
        "pip ecosystem watches directory '/' and cannot be told to skip one "
        "file, so it will propose per-package bumps of guarddog's own "
        "transitive pins and the required GuardDog check will go red before "
        "the scanner runs (#307)."
    )
    watched = _pip_ecosystem()["directory"]
    assert watched == "/", (
        f"the pip ecosystem now watches {watched!r} rather than '/'. This gate "
        "assumed the root; re-derive whether ci/guarddog/ is inside it."
    )
    relative = LOCK.relative_to(REPO_ROOT).as_posix()
    assert "/" in relative, (
        f"{relative} sits directly in the watched root again"
    )


def test_upstream_pins_are_not_ignored_by_name() -> None:
    ignored = {
        entry.get("dependency-name")
        for entry in _pip_ecosystem().get("ignore", [])
    }
    for name in UPSTREAM_PINS:
        assert name not in ignored, (
            f"{name} is back in dependabot.yml's ignore list. It is guarddog's "
            "transitive pin, not our dependency: the reason it once needed an "
            "ignore was the lock's placement, and that was fixed by moving the "
            "file (#307). Name-by-name ignores do not scale -- guarddog's "
            "transitive set changes with every release."
        )


def test_every_reference_points_at_the_new_path() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")
    assert "--require-hashes -r ci/guarddog/requirements.txt" in workflow, (
        "the GuardDog job no longer installs from ci/guarddog/requirements.txt"
    )
    assert "requirements-guarddog.txt" not in workflow, (
        "guarddog.yml still names the old root path"
    )
    # The ratchet's docstring quotes the install command it once mis-parsed
    # (#231). A stale path there teaches the next reader the wrong layout.
    assert "requirements-guarddog.txt" not in RATCHET.read_text(encoding="utf-8")


def test_the_lock_is_not_swept_up_by_the_relock_workflow() -> None:
    """`requirements-*.in` is regenerated wholesale; this input must not be.

    `.github/workflows/relock-dependabot.yml` loops over
    ``requirements-*.in`` in its working directory and recompiles each with
    uv. Running that over guarddog's input would re-resolve the scanner's
    closure on a schedule nobody reviewed -- the floating behaviour the lock
    exists to prevent.

    Asserting `LOCK_IN.name not in glob("requirements-*.in")` would prove
    nothing: the file is called `requirements.in`, with no hyphen, so it
    fails that glob wherever it sits. The real question is whether the
    workflow's loop could reach it, so the loop's own glob is applied to the
    path relative to the directory the workflow runs in.
    """
    assert LOCK_IN.is_file(), "ci/guarddog/requirements.in is missing"
    workflow = RELOCK.read_text(encoding="utf-8")
    pattern_line = "for in_file in requirements-*.in; do"
    assert pattern_line in workflow, (
        "relock-dependabot.yml no longer loops over requirements-*.in; this "
        "gate is asserting against a pattern that is gone, re-derive it"
    )
    # The loop runs in the checkout root with no `cd`, so its glob is
    # non-recursive and anchored there. Both facts are load-bearing: a `cd`
    # or an `**` would change which files it reaches.
    assert "\n          cd " not in workflow, (
        "the relock workflow now changes directory; re-check which files its "
        "requirements-*.in loop can reach"
    )
    relative = LOCK_IN.relative_to(REPO_ROOT)
    assert not fnmatch.fnmatch(relative.as_posix(), "requirements-*.in"), (
        f"{relative.as_posix()} matches the relock loop's glob"
    )
    # And the decisive one: enumerate what that loop would actually pick up.
    reachable = {p.relative_to(REPO_ROOT) for p in REPO_ROOT.glob("requirements-*.in")}
    assert relative not in reachable, (
        f"{relative.as_posix()} is reachable by the relock loop; renaming it "
        "to requirements-<something>.in in the root would put guarddog's "
        "closure back on an unreviewed regeneration schedule"
    )
    assert reachable, (
        "the relock loop reaches no .in files at all -- this gate is looking "
        "in the wrong place and would pass by default"
    )


def test_the_pair_is_still_covered_by_the_freshness_gate() -> None:
    """Out of Dependabot's reach must not mean out of every gate's reach.

    `scripts/check_lock_freshness.py` discovers root `requirements-*.in`
    files by glob. Moving this pair out of the root removed it from that
    discovery, which would let a hand-edited transitive pin -- a plausible
    looking one-line diff -- land without proving it came from a whole-lock
    regeneration. The script therefore carries an explicit EXTRA_PAIRS entry,
    and this asserts the pair is really in it rather than trusting the
    comment.
    """
    spec = importlib.util.spec_from_file_location("check_lock_freshness", FRESHNESS)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    covered = {
        pathlib.Path(in_path).resolve() for in_path, _ in module.EXTRA_PAIRS
    }
    assert LOCK_IN.resolve() in covered, (
        "ci/guarddog/requirements.in is not in check_lock_freshness.EXTRA_PAIRS; "
        "the pair sits outside the root glob, so nothing else checks that the "
        "lock still matches its input"
    )
    # The gate must agree with reality right now, not merely mention the path.
    assert module.check_paths(LOCK_IN, LOCK) == []


def test_dependabot_is_told_to_skip_the_directory() -> None:
    """The move alone is not the fix; `exclude-paths` is the other half.

    `directory: "/"` does not confine the pip ecosystem to the root -- it
    scans subdirectories too (dependabot-core#11360 asked for the opposite
    behaviour and the change was reverted). So relocating the lock without
    excluding it would leave the bot finding the file at its new path and
    resuming exactly the per-package bumps that broke the required GuardDog
    check. `exclude-paths` applies before manifest parsing, so nothing under
    the excluded prefix is listed, parsed, or turned into a pull request.
    """
    patterns = _pip_ecosystem().get("exclude-paths") or []
    relative = LOCK.relative_to(REPO_ROOT).as_posix()
    assert any(fnmatch.fnmatch(relative, pattern) for pattern in patterns), (
        f"{relative} is not covered by exclude-paths {patterns!r}. The "
        "subdirectory alone does not hide it: the pip ecosystem scans below "
        "its directory, so without this the per-package bumps come back."
    )
    assert any(
        fnmatch.fnmatch(LOCK_IN.relative_to(REPO_ROOT).as_posix(), pattern)
        for pattern in patterns
    ), "the input is excluded too, or Dependabot will parse it instead"


def test_the_input_pins_guarddog_exactly() -> None:
    """An exact pin, so the closure in the lock is the one upstream shipped."""
    lines = [
        line.strip()
        for line in LOCK_IN.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]
    assert lines == [
        line for line in lines if line.startswith("guarddog==")
    ], f"ci/guarddog/requirements.in should hold one exact guarddog pin; got {lines}"
    assert len(lines) == 1, (
        "more than one requirement in the guarddog input: every other package "
        f"in the lock must arrive as guarddog's transitive dependency, got {lines}"
    )
    pinned = lines[0].split("==", 1)[1]
    locked = [
        line
        for line in LOCK.read_text(encoding="utf-8").splitlines()
        if line.startswith("guarddog==")
    ]
    assert locked, "the lock does not pin guarddog itself"
    assert locked[0].split("==", 1)[1].split()[0].rstrip("\\").strip() == pinned, (
        "ci/guarddog/requirements.in and requirements.txt disagree on the "
        "guarddog version; regenerate the lock from the input in the same commit"
    )
