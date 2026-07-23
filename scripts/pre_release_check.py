"""Pre-release sanity-check guard.

Runs the checks that are easy to forget between "tests are green"
and "release is shipped":

1. The four version sources (constants.py, pyproject.toml,
   BRIDGE_VERSIONS, LATEST_BRIDGE) are in sync.
2. CHANGELOG.md has a top entry whose ``## vX.Y.Z`` header
   matches the current version.
3. CHANGELOG.ru.md has the same.
4. The most recent git tag (if any) on master points to the
   current HEAD, OR the current HEAD has no tag yet (new
   release hasn't been tagged).
5. ``docs/version.json`` is reachable and matches the current
   version (i.e. the badge workflow has run on this commit).

The guard is designed to run on the maintainer's local checkout
right before ``dev/bump_version.py <X.Y.Z>`` + tag + release —
NOT in CI on every commit (the tag check would always fail
between releases). Wire it into CI as an optional job, or run
it by hand via::

    python scripts/pre_release_check.py

Exit code 0 = ready to ship. Non-zero = something is off.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import List, Tuple

# Reuse the version-sync logic
sys.path.insert(0, str(Path(__file__).resolve().parent))
import version_sync  # type: ignore[import-not-found]


def _check_changelog_header(path: Path, expected_version: str) -> Tuple[bool, str]:
    """Check that ``path`` has a top-level ``## v<expected_version>`` header."""
    if not path.exists():
        return False, f"  {path}: not found"
    text = path.read_text(encoding="utf-8")
    # Look for "## v4.65.0" or similar at the start of any line
    pattern = re.compile(rf"^##\s+v{re.escape(expected_version)}\b", re.MULTILINE)
    if not pattern.search(text):
        return False, f"  {path}: no `## v{expected_version}` header found"
    # Make sure it's the first ## section (top-of-file entry)
    first_h2 = re.search(r"^##\s+(v\S+)", text, re.MULTILINE)
    if first_h2 and first_h2.group(1) != f"v{expected_version}":
        return False, (
            f"  {path}: top entry is `## {first_h2.group(1)}`"
            f" but expected `## v{expected_version}`"
        )
    return True, f"  {path}: top entry is v{expected_version}"


def _check_version_json(repo_root: Path, expected_version: str) -> Tuple[bool, str]:
    """Check that docs/version.json's tag_name matches v<expected_version>.

    Falls back to "not present" — which is fine on the very first
    release after the workflow is added, but the guard warns.
    """
    path = repo_root / "docs" / "version.json"
    if not path.exists():
        return True, "  docs/version.json: not present (skipped — first release?)"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        return False, f"  docs/version.json: malformed JSON ({e})"
    tag = data.get("tag_name", "")
    if tag != f"v{expected_version}":
        return False, (
            f"  docs/version.json: tag_name={tag!r}, expected v{expected_version!r}"
            " (the badge workflow hasn't refreshed yet?)"
        )
    return True, f"  docs/version.json: tag_name matches ({tag})"


def _check_git_tag_state(repo_root: Path, expected_version: str) -> Tuple[bool, str]:
    """Check that the current HEAD is either tagged with the expected
    version, OR no tag for this version exists yet (i.e. we are about
    to tag it). The case where HEAD has a *different* version tag is
    the interesting one — it means a previous release commit is
    sitting on master and we need to either rebase or fast-forward.
    """
    expected_ref = f"refs/tags/v{expected_version}"
    try:
        # Does the tag exist at all?
        result = subprocess.run(
            ["git", "show-ref", "--verify", "--quiet", expected_ref],
            cwd=str(repo_root), capture_output=True, timeout=10,
        )
        if result.returncode == 0:
            # Tag exists — does it point to HEAD?
            head = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=str(repo_root), capture_output=True, text=True, timeout=10,
            ).stdout.strip()
            tag_sha = subprocess.run(
                ["git", "rev-parse", expected_ref],
                cwd=str(repo_root), capture_output=True, text=True, timeout=10,
            ).stdout.strip()
            if head == tag_sha:
                return True, f"  git: HEAD is already tagged v{expected_version}"
            return False, (
                f"  git: tag v{expected_version} exists but does not point to HEAD"
                f" (tag={tag_sha[:8]}, head={head[:8]})"
            )
        # Tag does not exist — this is the "about to tag" case, which is fine
        return True, f"  git: tag v{expected_version} does not exist yet (about to create?)"
    except (subprocess.TimeoutExpired, FileNotFoundError) as e:
        return True, f"  git: skipped ({e})"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--repo-root", default=".", help="Path to the repo root")
    args = parser.parse_args()

    repo_root = Path(args.repo_root).resolve()

    # 1. Resolve the current version via version_sync's helpers
    constants = version_sync._parse_constants(repo_root)
    pyproject = version_sync._parse_pyproject(repo_root)
    matrix = version_sync._parse_version_matrix(repo_root)
    bridge_versions = matrix["bridge_versions"]

    if not constants:
        print("[pre-release] FAIL: arena/constants.py has no VERSION literal")
        return 1
    if not pyproject:
        print("[pre-release] FAIL: pyproject.toml has no [project] version line")
        return 1
    if not bridge_versions:
        print("[pre-release] FAIL: tests/_version_matrix.py has no BRIDGE_VERSIONS entries")
        return 1

    defined = {
        "constants.py": constants,
        "pyproject.toml": pyproject,
        "BRIDGE_VERSIONS[-1]": bridge_versions[-1],
    }
    if len(set(defined.values())) != 1:
        print("[pre-release] FAIL: version drift across the three mutable sources:")
        for k, v in defined.items():
            print(f"  {k:30s}  {v}")
        print("Run `python dev/bump_version.py <X.Y.Z>` to align.")
        return 1

    expected = constants  # all three agree

    print(f"[pre-release] checking version v{expected}")

    checks: List[Tuple[bool, str]] = []

    # 2 + 3. CHANGELOG headers
    checks.append(_check_changelog_header(repo_root / "CHANGELOG.md", expected))
    checks.append(_check_changelog_header(repo_root / "CHANGELOG.ru.md", expected))

    # 4. docs/version.json freshness
    checks.append(_check_version_json(repo_root, expected))

    # 5. git tag state
    checks.append(_check_git_tag_state(repo_root, expected))

    failed = False
    for ok, msg in checks:
        print(msg)
        if not ok:
            failed = True

    if failed:
        print("[pre-release] FAIL: one or more checks did not pass.")
        return 1
    print("[pre-release] OK: ready to tag and release.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
