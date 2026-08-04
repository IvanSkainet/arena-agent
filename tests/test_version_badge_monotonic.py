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


def test_badge_never_claims_a_version_that_does_not_exist_yet():
    """The badge may trail the tree, but must never lead it.

    An earlier version of this test asserted ``badge >= VERSION`` -- that the
    badge never lags.  That assertion is *unsatisfiable on the one commit that
    matters*, and it took a release to notice: the release commit bumps
    ``arena/constants.py`` and is pushed *before* `version-badge.yml` can run,
    so at that commit the badge is still the previous release, by
    construction.  Measured across the release commits in history:

        7041c57d  tree=4.159.0  badge=4.158.0
        91ffb312  tree=4.154.0  badge=4.153.3
        2cbfc6b4  tree=4.153.3  badge=4.153.2

    The whole test matrix (15 jobs) went red on v4.159.0 for this reason, on
    a repository where nothing was actually wrong.  A gate that cannot pass
    when the system is healthy is not a gate, it is an alarm that has to be
    ignored -- and an alarm that gets ignored is how a real one gets missed.

    The real property is one-sided.  The badge is published *from* a release,
    so it can legitimately trail the working tree between the bump and the
    workflow run; what it must never do is announce a version that was never
    shipped, which is what the v4.158.0 race produced (a stale API read wrote
    an *older* version over a newer one).  Leading the tree means the badge
    invented a release.  Trailing it by more than one minor means the badge
    workflow has been silently dead for several releases, which is the other
    failure worth catching.
    """
    from arena.constants import VERSION

    badge = json.loads(BADGE.read_text(encoding="utf-8"))

    def parts(v):
        return tuple(int(x) for x in v.split("."))

    badge_v, tree_v = parts(badge["semver"]), parts(VERSION)

    assert badge_v <= tree_v, (
        f"badge says {badge['semver']} but the tree is only {VERSION}; the "
        "badge is advertising a release that does not exist")

    # Trailing is expected, but only briefly: at most one minor behind.
    if badge_v[:2] != tree_v[:2]:
        assert badge_v[0] == tree_v[0] and tree_v[1] - badge_v[1] <= 1, (
            f"badge ({badge['semver']}) is more than one minor behind the "
            f"tree ({VERSION}); the badge workflow has probably been failing "
            "silently for several releases")

    assert badge["tag_name"] == f"v{badge['semver']}"
