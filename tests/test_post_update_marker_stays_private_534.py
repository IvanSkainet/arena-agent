"""A post-update smoke marker must not reach a home that tests share."""

# One marker left in the shared home made the next test that started a bridge
# run the real ship smoke on an executor thread; its `systemctl` and `loginctl`
# calls, its `<home>/update` directory and its flight record then turned up in
# unrelated tests (#518, #534, #555, #587).

from __future__ import annotations

import pytest

from arena.ship import post_update_smoke as P
from tests._post_update_marker import marker_stays_out_of

# --- looking at the state creates nothing (#518) ----------------------------


def test_a_status_read_leaves_a_fresh_home_empty(monkeypatch, tmp_path):
    """`status()` only looks."""
    monkeypatch.setenv("ARENA_AGENT_HOME", str(tmp_path))

    state = P.status()

    assert state["state"] == "unknown"
    assert list(tmp_path.iterdir()) == []


def test_a_startup_with_nothing_pending_leaves_a_fresh_home_empty(monkeypatch, tmp_path):
    """`run_if_pending()` is what every bridge start calls."""
    monkeypatch.setenv("ARENA_AGENT_HOME", str(tmp_path))

    outcome = P.run_if_pending()

    assert outcome["attempted"] is False
    assert list(tmp_path.iterdir()) == []


# --- the writers create the directory themselves ----------------------------


def test_marking_still_creates_the_directory_it_needs(monkeypatch, tmp_path):
    """The writer makes `<home>/update` itself now that the readers do not."""
    monkeypatch.setenv("ARENA_AGENT_HOME", str(tmp_path))

    marked = P.mark_pending({"tag": "vX"})

    assert marked["pending_path"] == str(tmp_path / "update" / "post-update-smoke-pending.json")
    assert P.status()["pending_record"]["tag"] == "vX"


def test_the_result_is_written_even_if_the_directory_went_away(monkeypatch, tmp_path):
    """Whoever cleaned up during the smoke does not lose its result."""
    monkeypatch.setenv("ARENA_AGENT_HOME", str(tmp_path))
    P.mark_pending({"tag": "vX"})

    class _Smoke:
        @staticmethod
        def run():
            P.pending_path().unlink()
            (tmp_path / "update").rmdir()
            return {"ok": True, "mode": "nominal"}

    import arena.ship

    monkeypatch.setattr(arena.ship, "smoke", _Smoke, raising=False)

    outcome = P.run_if_pending()

    assert outcome["ok"] is True
    assert P.status()["last"]["smoke"]["mode"] == "nominal"


# --- the guard around every test ---------------------------------------------


def test_a_marker_written_during_a_test_fails_that_test_and_is_removed(tmp_path):
    """The test that writes it is the one that hears about it."""
    marker = tmp_path / "update" / "post-update-smoke-pending.json"
    marker.parent.mkdir()

    def a_test_that_writes_the_marker():
        with marker_stays_out_of(marker):
            marker.write_text("{}", encoding="utf-8")

    with pytest.raises(pytest.fail.Exception, match="left .* behind"):
        a_test_that_writes_the_marker()

    assert not marker.exists()


def test_a_marker_that_was_already_there_is_left_alone(tmp_path):
    """On a developer's machine it can be a real one."""
    marker = tmp_path / "post-update-smoke-pending.json"
    marker.write_text("{}", encoding="utf-8")

    with marker_stays_out_of(marker):
        marker.write_text('{"again": true}', encoding="utf-8")

    assert marker.exists()


def test_a_test_that_writes_no_marker_is_not_charged(tmp_path):
    """Nothing before, nothing after: nothing to say."""
    marker = tmp_path / "post-update-smoke-pending.json"

    with marker_stays_out_of(marker):
        (tmp_path / "something-else.json").write_text("{}", encoding="utf-8")

    assert not marker.exists()
