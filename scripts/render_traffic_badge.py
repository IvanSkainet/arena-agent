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
**14-day** window. This is a traffic signal, not a count of people; automation can clone too.

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
BLOCK = re.compile(re.escape(BEGIN) + r".*?" + re.escape(END), re.S)


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
    return parse_counts(data)


def _clone_count(value: object) -> int:
    if isinstance(value, bool):
        raise SystemExit("traffic badge: invalid boolean clone count")
    if not isinstance(value, int):
        raise SystemExit("traffic badge: invalid clone count type")
    if value < 0:
        raise SystemExit("traffic badge: invalid negative clone count")
    return value


def parse_counts(data: object) -> tuple[int, int]:
    if not isinstance(data, dict):
        raise SystemExit("traffic badge: invalid traffic response")
    uniques = _clone_count(data.get("uniques"))
    total = _clone_count(data.get("count"))
    if uniques > total:
        raise SystemExit("traffic badge: invalid clone counts; uniques exceed total")
    return uniques, total



def badge_markup(uniques: int, total: int, measured: str) -> str:
    """Static shields.io badge plus the caveat that makes it honest."""
    colour = "blue"  # Traffic volume is not a popularity or human-user rating.
    label = "unique%20clones%20(14d)"
    return (
        f"{BEGIN}\n"
        f"![Unique clones (14 days)]"
        f"(https://img.shields.io/badge/{label}-{uniques}-{colour})\n"
        f"\n"
        f"<sub>{uniques} unique cloners over the 14 days to {measured} "
        f"({total} clones total). Daily refresh proposals are opened by "
        f"`.github/workflows/traffic-badge.yml` and reach README only after "
        f"normal protected PR review and checks. GitHub keeps a rolling "
        f"14-day window. Unique cloners are not verified people and may "
        f"include automation. Release-download counts also include automation "
        f"and retries; v4.169.50 reported 349 downloads of one ZIP and 3 of "
        f"its byte-identical alias, which does not establish a human user count.</sub>\n"
        f"{END}"
    )


def render(readme: str, block: str) -> str:
    if BLOCK.search(readme):
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
                        help="update README.md locally; publishing is a separate protected PR step")
    parser.add_argument("--check", action="store_true",
                        help="exit 1 if the badge block is missing")
    args = parser.parse_args(argv)

    readme = README.read_text(encoding="utf-8")

    if args.check:
        return check_block(readme)
    return refresh_snapshot(readme, write=args.write)


def check_block(readme: str) -> int:
    if BLOCK.search(readme) is None:
        print("traffic badge: README.md has no badge block")
        return 1
    print("traffic badge: block present")
    return 0


def refresh_snapshot(readme: str, *, write: bool) -> int:
    uniques, total = fetch_uniques()
    measured = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    updated = render(readme, badge_markup(uniques, total, measured))

    if updated == readme:
        print(f"traffic badge: unchanged ({uniques} uniques)")
        return 0

    if not write:
        print(f"traffic badge: would set {uniques} uniques / {total} clones")
        return 0

    README.write_text(updated, encoding="utf-8")
    print(f"traffic badge: {uniques} uniques, {total} clones, measured {measured}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
