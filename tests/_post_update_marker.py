"""Fail the test that leaves a post-update smoke marker in a home it shares."""

# `<home>/update/post-update-smoke-pending.json` is an instruction to the next
# bridge that starts: run the ship smoke.  A test that leaves one in the home
# the other tests also use hands that instruction to whichever test starts a
# bridge next.  The smoke then runs on the bridge's executor thread for a few
# seconds and outlives that test: it starts `systemctl` and `loginctl`, creates
# `<home>/update` and writes a flight record, all under the tests that follow.
#
# Four failures came from this one file, each in a test that had nothing to do
# with it: #518 (a directory appeared), #534 (`loginctl` was recorded), #555
# (two smoke records after one run) and #587 (`systemctl` was recorded).  Each
# was seen once and passed on re-run, because the order of tests is random.
#
# So the test that writes the marker is the one that fails, by name, and the
# marker is removed so that it does not also fail the tests after it.
#
# What "the home it shares" means: the home in force when the test's fixtures
# begin, which is the one a test gets when it names none.  A test that points
# `ARENA_AGENT_HOME` at its own `tmp_path` writes there and is not affected.
# A marker that was already present is left alone: on a developer's machine it
# can be a real one.
#
# Limit: in a serial run every test shares the account's home, so a marker
# written there by another process while a test runs is charged to that test.

from __future__ import annotations

import contextlib
from collections.abc import Iterator
from pathlib import Path

import pytest


@contextlib.contextmanager
def marker_stays_out_of(marker: Path) -> Iterator[None]:
    """Fail if `marker` did not exist before the block and exists after it."""
    present_before = marker.exists()
    yield
    if present_before or not marker.exists():
        return
    marker.unlink()
    pytest.fail(
        f"this test left {marker} behind, in a home other tests share. The next "
        "bridge a test starts would run the real ship smoke on an executor "
        "thread, under whichever tests come next. Point ARENA_AGENT_HOME at "
        "tmp_path with monkeypatch.setenv, or replace "
        "arena.ship.post_update_smoke.mark_pending. The marker was removed.",
        pytrace=False,
    )


@pytest.fixture(autouse=True)
def _no_post_update_marker_in_a_shared_home() -> Iterator[None]:
    """Watch the shared home's marker around every test."""
    # Imported here: a worker is moved to directories of its own after this
    # plugin is imported and before the first test, and no product module
    # should be loaded ahead of that move on this plugin's account.
    from arena.ship import post_update_smoke

    with marker_stays_out_of(post_update_smoke.pending_path()):
        yield
