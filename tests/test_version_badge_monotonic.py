"""The version badge may never move backwards.

Cutting a release fires `version-badge.yml` twice: once for the tag (which
knows its own name) and once for the push to master (which asks the API for
`releases/latest`). Those two race, and on v4.158.0 the race was lost in the
worst possible way -- both runs reported success, so nothing looked broken:

    22:00:14  tag run    -> wrote 4.158.0
    22:01:13  push run   -> overwrote it with 4.157.0
    22:01:22  the release actually became "latest"

The push run asked the API 9 seconds too early, got the previous release, and
faithfully published a badge that told every reader the project had gone back
a version.

The fix is not tighter timing -- ordering between two workflow runs is not
something we control. It is refusing to write a version older than the one on
disk, which makes the race harmless in either order. This test pins the
comparison logic extracted from that step, including the case a naive string
compare gets wrong (4.9.0 -> 4.10.0).
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
WORKFLOW = REPO / ".github" / "workflows" / "version-badge.yml"
BADGE = REPO / "docs" / "version.json"


def _decide(current: str, incoming: str) -> bool:
    """Mirror of the workflow step: True means 'skip the write'."""
    def parts(v: str) -> tuple[int, ...]:
        try:
            return tuple(int(x) for x in v.split("."))
        except ValueError:
            return ()

    new, old = parts(incoming), parts(current)
    return bool(new and old and new < old)


@pytest.mark.parametrize(("current", "incoming", "skip"), [
    ("4.157.0", "4.158.0", False),   # normal forward move
    ("4.158.0", "4.157.0", True),    # the actual v4.158.0 race
    ("4.158.0", "4.158.0", False),   # idempotent rewrite is fine
    ("4.158.0", "4.159.0", False),
    ("4.9.0", "4.10.0", False),      # string compare would call this backwards
    ("4.10.0", "4.9.0", True),
    ("", "4.158.0", False),          # no previous badge
    ("abc", "4.158.0", False),       # unparseable: do not block the write
    ("4.158.0", "abc", False),       # unparseable incoming: let it through
])
def test_backwards_moves_are_skipped(current, incoming, skip):
    assert _decide(current, incoming) is skip


def test_workflow_actually_guards_both_write_steps():
    """The guard is worthless if only one of the two steps honours it."""
    src = WORKFLOW.read_text(encoding="utf-8")
    assert "Refuse to move the badge backwards" in src, (
        "the monotonicity step is gone from version-badge.yml")
    guarded = re.findall(r"if:\s*steps\.monotonic\.outputs\.skip != 'true'", src)
    assert len(guarded) >= 2, (
        "both 'Write docs/version.json' and 'Commit if changed' must be gated "
        f"on the monotonicity check; found {len(guarded)} guard(s)")


def test_badge_matches_the_shipped_version():
    """docs/version.json must not lag behind arena.constants.VERSION."""
    from arena.constants import VERSION

    badge = json.loads(BADGE.read_text(encoding="utf-8"))
    def parts(v):
        return tuple(int(x) for x in v.split("."))

    assert parts(badge["semver"]) >= parts(VERSION), (
        f"badge says {badge['semver']} but the tree is {VERSION}; the badge "
        "went backwards or a release was cut without refreshing it")
    assert badge["tag_name"] == f"v{badge['semver']}"
