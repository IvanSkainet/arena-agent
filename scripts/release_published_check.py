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
from release_withdrawals import withdrawal_credit

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


def _request_headers() -> dict[str, str]:
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "arena-release-check"}
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _decode_response(payload: bytes) -> dict | list | None:
    value = json.loads(payload.decode("utf-8"))
    return value if isinstance(value, (dict, list)) else None


def _http_error(exc: urllib.error.HTTPError, authenticated: bool) -> dict:
    if exc.code == 404:
        return {}
    if exc.code == 403 and not authenticated:
        raise RuntimeError(
            "GitHub rate-limited this anonymous request; set GITHUB_TOKEN "
            "so the check can actually see releases/latest"
        ) from exc
    raise exc


def _api(path: str) -> dict | list | None:
    url = f"https://api.github.com/repos/{REPO}{path}"
    headers = _request_headers()
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:  # nosec B310 -- fixed api.github.com host
            return _decode_response(resp.read())
    except urllib.error.HTTPError as exc:
        return _http_error(exc, "Authorization" in headers)


def _unavailable(tag: str, reason: str, strict: bool) -> int:
    print(f"release check: SKIPPED ({reason})")
    print(f"  tree is at {tag}; verify it is published before calling the release done")
    return 1 if strict else 0


def tags_without_releases() -> list[str]:
    """Local tags that are ahead of the newest published release."""
    out = subprocess.run(["git", "tag", "--list", "v*"], cwd=REPO_ROOT,
                         capture_output=True, text=True, timeout=60)
    return [t.strip() for t in out.stdout.splitlines() if t.strip()]


# A minor/major bump cannot be counted in patch releases -- 4.170.0 is
# "one release" after 4.169.50 in intent, but there is no patch distance
# between them at all.
_ADJACENT = 1
_FAR_AHEAD = 99


def _gap(tree: tuple[int, ...], published: tuple[int, ...]) -> int:
    """How many releases the tree is ahead.

    Within one minor line this is the patch distance. Across lines it is
    a judgement: an *adjacent* minor or major bump is one step, because
    RELEASE.md step 3 commits the version to master before the release
    is cut, so the tree is legitimately one ahead for the length of the
    release PR. Anything further is still treated as a pile-up.

    This used to return 99 for every minor jump, which caused two
    problems. The message read "99 unpublished releases have piled up",
    a number that counts nothing -- I went looking for 99 drafts and
    found two. And 99 exceeds the lead the non-strict path allows, so
    `Version sync` -- a required check -- went red on the release PR
    itself, making a minor release unmergeable without bypassing the
    ruleset. Patch releases scored 1 and passed, which is why this
    survived to v4.170.0.

    The first fix was too broad: scoring *any* cross-line bump as one
    step let a tree three majors ahead of the published release through,
    which `test_release_check_distinguishes_no_answer_from_no_problem`
    caught (it asserts a v1.0.0 release against a 4.x tree still fails).
    Adjacency is the property that matters, not merely "the line
    changed".
    """
    if not tree or not published:
        return 0
    if tree[:2] == published[:2]:
        return max(0, (tree[2] if len(tree) > 2 else 0)
                   - (published[2] if len(published) > 2 else 0))
    # Same major, next minor: 4.169.x -> 4.170.0
    if tree[0] == published[0] and tree[1] == published[1] + 1:
        return _ADJACENT
    # Next major, reset minor: 4.x -> 5.0
    if tree[0] == published[0] + 1 and tree[1] == 0:
        return _ADJACENT
    return _FAR_AHEAD



def _checked_gap(tree: tuple, latest: tuple, strict: bool) -> int:
    gap = _gap(tree, latest)
    if strict or gap <= 1:
        return gap
    return gap - withdrawal_credit(tree, latest, _api, REPO)


def _debt_problem(version: str, latest_tag: str, gap: int) -> str:
    pile = f"{gap} unpublished releases have piled up; " if gap > 1 else ""
    return (
        f"{pile}the tree is at v{version} but releases/latest is "
        f"{latest_tag or '(none)'} -- auto_update.py reads releases/latest, "
        "so every install is stuck there"
    )


def _publication_debt(version: str, latest_tag: str, strict: bool) -> list[str]:
    try:
        gap = _checked_gap(source_parts(version), release_tag_parts(latest_tag), strict)
    except (ValueError, OSError, RuntimeError) as exc:
        return [f"withdrawal evidence could not be verified: {exc}"]
    allowed = 0 if strict else 1
    return [_debt_problem(version, latest_tag, gap)] if gap > allowed else []


def _version_problems(version: str, latest_tag: str, strict: bool) -> list[str]:
    tree = source_parts(version)
    latest = release_tag_parts(latest_tag)
    if not tree:
        return [f"the source VERSION {version!r} must match the strict X.Y.Z contract"]
    if not latest:
        return [f"releases/latest tag {latest_tag!r} must match the strict vX.Y.Z contract"]
    if latest > tree:
        return [
            f"releases/latest {latest_tag} is ahead of the source tree v{version}; "
            "published metadata cannot advertise code that master does not contain"
        ]
    if latest < tree:
        return _publication_debt(version, latest_tag, strict)
    return []


def main(argv: list[str]) -> int:
    strict = "--strict" in argv
    # Locally the tree is legitimately one release ahead: the bump is
    # committed before the release is cut. What is NOT legitimate is the
    # gap growing -- v4.169.5..9 piled up five deep before anyone noticed.
    # `--strict` (CI, tags only) demands the release actually exists.
    version = current_version()
    tag = f"v{version}"

    try:
        latest = _api("/releases/latest")
    except Exception as exc:  # noqa: BLE001 -- offline preflight semantics are unchanged
        return _unavailable(tag, f"GitHub unreachable: {exc}", strict)

    if not isinstance(latest, dict):
        return _unavailable(tag, "no usable answer from GitHub", strict)

    latest_tag = str(latest.get("tag_name") or "")
    names = {a.get("name") for a in (latest.get("assets") or [])}

    problems = _version_problems(version, latest_tag, strict)
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
