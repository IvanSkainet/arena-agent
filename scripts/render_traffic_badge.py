#!/usr/bin/env python3
"""Render a unique-clones badge into README.md from the traffic API.

Why not the release download counter, which is the obvious choice:
v4.169.50 reported **349** downloads of ``arena-agent-v4.169.50.zip``
and **3** of ``arena-agent.zip`` -- two names for one build with the
same sha256, so a human browsing the release page would have pulled
them at roughly equal rates. The ``.sig`` files sat at 0, meaning nobody
verified a signature. The number is mostly auto-update retries and
bots, and it only ever goes up.

``/traffic/clones`` reports ``uniques``: distinct cloners over a rolling
**14-day** window. Smaller, and actually about people.

That window is the catch, and it decides the design. A badge committed
once would freeze at the day it was generated and slowly become a lie --
the same failure as every stale claim this repo has had to fix (#231,
#234, #240). So the value carries the date it was measured, and the
workflow refreshes it daily.

The endpoint needs push access, so this cannot be a shields.io dynamic
badge: an anonymous request gets 403. The badge is therefore static
markup regenerated in place.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
README = REPO_ROOT / "README.md"
REPO = os.environ.get("GITHUB_REPOSITORY", "IvanSkainet/arena-agent")

BEGIN = "<!-- BEGIN TRAFFIC BADGE -->"
END = "<!-- END TRAFFIC BADGE -->"


def _token() -> str | None:
    return os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")


def fetch_uniques() -> tuple[int, int]:
    """Return (unique cloners, total clones) for the last 14 days."""
    token = _token()
    if not token:
        raise SystemExit(
            "traffic badge: no GH_TOKEN/GITHUB_TOKEN. The traffic API "
            "requires push access; an anonymous request returns 403, which "
            "is why this cannot be a shields.io dynamic badge."
        )
    req = urllib.request.Request(
        f"https://api.github.com/repos/{REPO}/traffic/clones",
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "User-Agent": "arena-traffic-badge",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:  # nosec B310 -- fixed api.github.com host
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise SystemExit(
            f"traffic badge: GitHub returned HTTP {exc.code}. 403 usually "
            f"means the token lacks push access to {REPO}."
        ) from exc
    return int(data.get("uniques", 0)), int(data.get("count", 0))


def badge_markup(uniques: int, total: int, measured: str) -> str:
    """Static shields.io badge plus the caveat that makes it honest."""
    colour = "brightgreen" if uniques >= 100 else "blue" if uniques >= 20 else "lightgrey"
    label = "unique%20clones%20(14d)"
    return (
        f"{BEGIN}\n"
        f"![Unique clones (14 days)]"
        f"(https://img.shields.io/badge/{label}-{uniques}-{colour})\n"
        f"\n"
        f"<sub>{uniques} unique cloners over the 14 days to {measured} "
        f"({total} clones total). Refreshed daily by "
        f"`.github/workflows/traffic-badge.yml`; GitHub only keeps a "
        f"14-day window. Deliberately not a release-download count — "
        f"v4.169.50 showed 349 downloads of one asset against 3 of the "
        f"byte-identical copy, so that number measures automation, not "
        f"people.</sub>\n"
        f"{END}"
    )


def render(readme: str, block: str) -> str:
    if BEGIN in readme and END in readme:
        return re.sub(
            re.escape(BEGIN) + r".*?" + re.escape(END),
            lambda _: block,
            readme,
            flags=re.S,
        )
    # First run: place it directly after the metrics block so the two
    # measured numbers sit together rather than drifting apart.
    anchor = "<!-- END GENERATED METRICS -->"
    if anchor in readme:
        return readme.replace(anchor, f"{anchor}\n\n{block}", 1)
    raise SystemExit(
        "traffic badge: no insertion point found in README.md; expected "
        f"either the badge markers or {anchor!r}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true",
                        help="update README.md and commit if it changed")
    parser.add_argument("--check", action="store_true",
                        help="exit 1 if the badge block is missing")
    args = parser.parse_args(argv)

    readme = README.read_text(encoding="utf-8")

    if args.check:
        missing = BEGIN not in readme or END not in readme
        if missing:
            print("traffic badge: README.md has no badge block")
            return 1
        print("traffic badge: block present")
        return 0

    uniques, total = fetch_uniques()
    measured = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    updated = render(readme, badge_markup(uniques, total, measured))

    if updated == readme:
        print(f"traffic badge: unchanged ({uniques} uniques)")
        return 0

    if not args.write:
        print(f"traffic badge: would set {uniques} uniques / {total} clones")
        return 0

    README.write_text(updated, encoding="utf-8")
    print(f"traffic badge: {uniques} uniques, {total} clones, measured {measured}")

    # Committing is part of the job: a scheduled run that edits a file and
    # walks away leaves the badge stale in the tree while claiming success.
    subprocess.run(["git", "config", "user.name", "github-actions[bot]"],
                   cwd=REPO_ROOT, check=True)
    subprocess.run(
        ["git", "config", "user.email",
         "41898282+github-actions[bot]@users.noreply.github.com"],
        cwd=REPO_ROOT, check=True)
    subprocess.run(["git", "add", "README.md"], cwd=REPO_ROOT, check=True)
    diff = subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=REPO_ROOT)
    if diff.returncode == 0:
        print("traffic badge: nothing to commit")
        return 0
    subprocess.run(
        ["git", "commit", "-m",
         f"chore: refresh unique-clones badge ({uniques} over 14d)"],
        cwd=REPO_ROOT, check=True)
    # Rebase first: the badge job races anything else pushing to master.
    subprocess.run(["git", "pull", "--rebase", "--autostash"],
                   cwd=REPO_ROOT, check=True)
    subprocess.run(["git", "push"], cwd=REPO_ROOT, check=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
