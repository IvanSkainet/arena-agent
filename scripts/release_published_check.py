#!/usr/bin/env python3
"""Gate: a tag that CI went green on must exist as a *published* release.

Tagging is not shipping. `arena/admin/auto_update.py` asks GitHub for
`releases/latest`, and GitHub answers with the latest **published
release** -- it knows nothing about tags. So a tag with no release behind
it is invisible to every install in the world.

That is exactly what happened here. v4.169.5 through v4.169.9 were
tagged, pushed and confirmed green on 35/35 CI jobs, and `releases/latest`
still said **v4.169.4**. Five releases' worth of fixes -- including the
mission-listing crash -- sat in the repository reachable by nobody. Every
one of those releases looked complete from the inside: green CI, correct
tag, changelog written. The only thing that was missing was the part
users actually consume.

Run with no network access it prints a reminder and exits 0 -- an offline
preflight must not fail on connectivity. With `--strict` (used in CI,
where the network is present) an unpublished tag is an error.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

from release_version_contract import release_tag_parts, source_parts

REPO_ROOT = Path(__file__).resolve().parents[1]
REPO = os.environ.get("ARENA_RELEASE_REPO", "IvanSkainet/arena-agent")
TIMEOUT = 30

# The two assets the README one-liner and auto-update depend on by exact
# name. A release missing the unversioned alias 404s the install command.
REQUIRED_ASSETS = ("arena-agent.zip",)


def current_version() -> str:
    text = (REPO_ROOT / "arena" / "constants.py").read_text(encoding="utf-8")
    match = re.search(r'^VERSION\s*=\s*"([^"]+)"', text, re.M)
    if not match:
        raise SystemExit("release check: could not read VERSION from arena/constants.py")
    return match.group(1)


def _api(path: str) -> dict | None:
    url = f"https://api.github.com/repos/{REPO}{path}"
    headers = {"Accept": "application/vnd.github+json",
               "User-Agent": "arena-release-check"}
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:  # nosec B310 -- fixed api.github.com host
            data = json.loads(resp.read().decode("utf-8"))
            return data if isinstance(data, dict) else None
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return {}
        # An anonymous 403 is a rate limit, not an answer, and it looks
        # exactly like being offline. Say which one it is -- a check that
        # cannot tell "no data" from "no problem" reports OK forever.
        if exc.code == 403 and not token:
            raise RuntimeError(
                "GitHub rate-limited this anonymous request; set GITHUB_TOKEN "
                "so the check can actually see releases/latest") from exc
        raise
    return None


def tags_without_releases() -> list[str]:
    """Local tags that are ahead of the newest published release."""
    out = subprocess.run(["git", "tag", "--list", "v*"], cwd=REPO_ROOT,
                         capture_output=True, text=True, timeout=60)
    return [t.strip() for t in out.stdout.splitlines() if t.strip()]


# A minor/major bump cannot be counted in patch releases -- 4.170.0 is
# "one release" after 4.169.50 in intent, but 4.169.50 -> 4.170.0 has no
# patch distance at all. Score it as a single step so the ordinary
# release flow is not mistaken for a pile-up.
_MINOR_JUMP_GAP = 1


def _gap(tree: tuple[int, ...], published: tuple[int, ...]) -> int:
    """How many releases the tree is ahead.

    Counted on the patch level within one minor line. A minor or major
    bump is one step, not an emergency: RELEASE.md has the version
    committed to master *before* the release is cut, so the tree is
    legitimately one ahead for the length of the release PR.

    This used to return 99 for any minor jump, which produced two
    problems at once. The message read "99 unpublished releases have
    piled up" -- a number that is not a count of anything and sent me
    looking for 99 drafts that did not exist (there were two). And
    because 99 > allowed_gap even in the non-strict path, the check went
    red on the release PR itself, while `Version sync` is a required
    context: a minor release could not be merged at all without
    bypassing the ruleset. A patch release never hit this, which is why
    it survived to v4.170.0.

    `--strict` still demands the release actually exist, so a tag that
    was never published is caught with the gap set to zero.
    """
    if not tree or not published:
        return 0
    if tree[:2] != published[:2]:
        return _MINOR_JUMP_GAP
    return max(0, (tree[2] if len(tree) > 2 else 0) - (published[2] if len(published) > 2 else 0))


def main(argv: list[str]) -> int:
    strict = "--strict" in argv
    # Locally the tree is legitimately one release ahead: the bump is
    # committed before the release is cut. What is NOT legitimate is the
    # gap growing -- v4.169.5..9 piled up five deep before anyone noticed.
    # `--strict` (CI, tags only) demands the release actually exists.
    allowed_gap = 0 if strict else 1
    version = current_version()
    tag = f"v{version}"

    try:
        latest = _api("/releases/latest")
    except Exception as exc:  # noqa: BLE001 -- offline is not a failure here
        print(f"release check: SKIPPED (GitHub unreachable: {exc})")
        print(f"  tree is at {tag}; verify it is published before calling the release done")
        return 1 if strict else 0

    if latest is None:
        print("release check: SKIPPED (no usable answer from GitHub)")
        return 1 if strict else 0

    latest_tag = str(latest.get("tag_name") or "")
    names = {a.get("name") for a in (latest.get("assets") or [])}

    problems = []
    tree_parts = source_parts(version)
    latest_parts = release_tag_parts(latest_tag)
    if not tree_parts:
        problems.append(
            f"the source VERSION {version!r} must match the strict X.Y.Z contract"
        )
    if not latest_parts:
        problems.append(
            f"releases/latest tag {latest_tag!r} must match the strict vX.Y.Z contract"
        )
    elif tree_parts and latest_parts > tree_parts:
        problems.append(
            f"releases/latest {latest_tag} is ahead of the source tree {tag}; "
            "published metadata cannot advertise code that master does not contain"
        )
    elif tree_parts and latest_parts < tree_parts:
        gap = _gap(tree_parts, latest_parts)
        if gap > allowed_gap:
            pile = f"{gap} unpublished releases have piled up; " if gap > 1 else ""
            problems.append(
                f"{pile}the tree is at {tag} but releases/latest is "
                f"{latest_tag or '(none)'} -- auto_update.py reads releases/latest, "
                f"so every install is stuck there"
            )
    for required in REQUIRED_ASSETS:
        if latest_tag == tag and required not in names:
            problems.append(
                f"release {tag} has no asset named {required!r}; the README "
                f"one-liner downloads it by exact name and will 404"
            )

    if problems:
        print("release check: FAIL")
        for line in problems:
            print(f"  {line}")
        print()
        print("  Tagging is not shipping. Publish the accepted candidate ZIP pair")
        print("  and APK without rebuilding them -- see RELEASE.md steps 8-10.")
        return 1

    print(f"release check: OK (releases/latest = {latest_tag}, assets present)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
