"""#120: resource listing helpers must not follow symlinks out of the root.

`Path.is_file()`/`is_dir()` follow symlinks, so a link planted in a resource
directory was listed as a genuine local entry, and for `.json` descriptors its
fields were parsed out of wherever it pointed and returned by the API.

Reproduced before the fix, on every helper at once: a single JSON file outside
the root, linked into all five directories, surfaced `status="PWNED"`,
`cmd="rm -rf /"`, `description="leaked"`, `model="exfil"` and
`event="on_start"` through `list_subagents`, `list_agents` and `list_hooks`.

`show_mission` is covered here too although the issue does not name it: it is
the worst of the six, because the listers surface selected fields while it
returns the *whole* linked file through `/v1/mission/show`.

What must stay working is as much of the contract as what must break: a
symlink pointing back inside the same root is a local reorganisation, not an
escape, and it stays listed.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest

from arena.resources.listing import (
    list_agents,
    list_hooks,
    list_missions,
    list_reports,
    list_subagents,
    show_mission,
)

PAYLOAD = {
    "status": "PWNED",
    "cmd": "rm -rf /",
    "description": "leaked",
    "model": "exfil",
    "event": "on_start",
}
SECRET_TEXT = "root:x:0:0:SUPER SECRET CONTENT\n"


@pytest.fixture
def outside(tmp_path: Path) -> Path:
    """A tree the resource root must never reach into."""
    out = tmp_path / "outside"
    out.mkdir()
    (out / "secret.json").write_text(json.dumps(PAYLOAD), encoding="utf-8")
    (out / "secret.txt").write_text(SECRET_TEXT, encoding="utf-8")
    linked_dir = out / "escaped"
    linked_dir.mkdir()
    (linked_dir / "inner.txt").write_text("inner", encoding="utf-8")
    return out


@pytest.fixture
def root(tmp_path: Path) -> Path:
    root = tmp_path / "home"
    root.mkdir()
    return root


def _names(entries: list[dict]) -> list[str]:
    return [e["name"] for e in entries]


# --- the escape ------------------------------------------------------------

def test_escaping_file_symlink_is_not_listed_by_any_helper(root, outside):
    """One planted link, every listing helper, no leaked fields."""
    for name in ("missions", "reports", "hooks", "agents", "subagents"):
        directory = root / name
        directory.mkdir()
        (directory / "link.json").symlink_to(outside / "secret.json")

    assert _names(list_missions(root / "missions")) == []
    assert _names(list_reports(root / "reports")) == []
    assert list_hooks(root / "hooks") == {"ok": True, "count": 0, "hooks": []}
    assert list_agents(root / "agents") == {"ok": True, "count": 0, "agents": []}
    assert list_subagents(root / "subagents") == {"ok": True, "count": 0, "subagents": []}


@pytest.mark.parametrize("field", sorted(PAYLOAD))
def test_no_field_from_outside_the_root_reaches_the_caller(root, outside, field):
    """The parsed descriptor fields are the actual disclosure."""
    for name in ("hooks", "agents", "subagents"):
        directory = root / name
        directory.mkdir()
        (directory / "link.json").symlink_to(outside / "secret.json")

    blob = json.dumps([
        list_hooks(root / "hooks"),
        list_agents(root / "agents"),
        list_subagents(root / "subagents"),
    ])
    assert PAYLOAD[field] not in blob


def test_escaping_directory_symlink_is_not_listed(root, outside):
    """The `[dir]` branches of list_agents/list_subagents/list_missions."""
    for name in ("missions", "agents", "subagents"):
        directory = root / name
        directory.mkdir()
        (directory / "linkdir").symlink_to(outside / "escaped", target_is_directory=True)

    assert _names(list_missions(root / "missions")) == []
    assert _names(list_agents(root / "agents")["agents"]) == []
    assert _names(list_subagents(root / "subagents")["subagents"]) == []


def test_shots_directory_may_itself_be_a_link_out(root, outside):
    """The case a per-entry `is_symlink()` check would miss.

    When `reports/shots` is the link, its entries are ordinary files: nothing
    about them is a symlink, yet their real location is outside the root.
    """
    reports = root / "reports"
    reports.mkdir()
    (reports / "shots").symlink_to(outside / "escaped", target_is_directory=True)

    assert _names(list_reports(reports)) == []


def test_show_mission_does_not_read_a_linked_file(root, outside):
    """The whole-file reader, not named in the issue but the worst path."""
    missions = root / "missions"
    missions.mkdir()
    (missions / "leak.txt").symlink_to(outside / "secret.txt")

    result = show_mission(missions, "leak")
    assert result["ok"] is False
    assert SECRET_TEXT not in json.dumps(result)


def test_show_mission_does_not_walk_a_linked_directory(root, outside):
    missions = root / "missions"
    missions.mkdir()
    (missions / "leakdir").symlink_to(outside / "escaped", target_is_directory=True)

    result = show_mission(missions, "leakdir")
    assert result["ok"] is False


def test_show_mission_directory_hides_escaping_children(root, outside):
    """A contained directory whose *child* escapes."""
    missions = root / "missions"
    missions.mkdir()
    real_dir = missions / "real"
    real_dir.mkdir()
    (real_dir / "ok.txt").write_text("fine", encoding="utf-8")
    (real_dir / "escape.txt").symlink_to(outside / "secret.txt")

    result = show_mission(missions, "real")
    assert result["ok"] is True
    assert [f["name"] for f in result["files"]] == ["ok.txt"]


# --- what must keep working ------------------------------------------------

def test_a_symlink_inside_the_same_root_stays_legal(root):
    """A local reorganisation is not an escape."""
    for name in ("missions", "hooks", "agents", "subagents"):
        directory = root / name
        directory.mkdir()
        (directory / "real.json").write_text(json.dumps(PAYLOAD), encoding="utf-8")
        (directory / "link.json").symlink_to(directory / "real.json")

    assert sorted(_names(list_missions(root / "missions"))) == ["link", "real"]
    assert sorted(_names(list_hooks(root / "hooks")["hooks"])) == ["link", "real"]
    assert sorted(_names(list_agents(root / "agents")["agents"])) == ["link", "real"]
    assert sorted(_names(list_subagents(root / "subagents")["subagents"])) == ["link", "real"]


def test_show_mission_still_reads_a_link_contained_in_the_root(root):
    missions = root / "missions"
    missions.mkdir()
    (missions / "real.txt").write_text("contained", encoding="utf-8")
    (missions / "link.txt").symlink_to(missions / "real.txt")

    assert show_mission(missions, "link")["content"] == "contained"


def test_ordinary_entries_are_untouched(root):
    missions = root / "missions"
    missions.mkdir()
    (missions / "a.json").write_text("{}", encoding="utf-8")
    sub = missions / "sub"
    sub.mkdir()
    (sub / "f.txt").write_text("y", encoding="utf-8")

    assert sorted(_names(list_missions(missions))) == ["a", "sub"]
    assert show_mission(missions, "a")["ok"] is True


def test_broken_symlinks_are_dropped(root, tmp_path):
    """`is_file()` already excluded these; strict resolution must not start
    listing them, and must not raise on them either."""
    for name in ("missions", "hooks", "agents", "subagents"):
        directory = root / name
        directory.mkdir()
        (directory / "broken.json").symlink_to(tmp_path / "does-not-exist.json")

    assert _names(list_missions(root / "missions")) == []
    assert list_hooks(root / "hooks")["count"] == 0
    assert list_agents(root / "agents")["count"] == 0
    assert list_subagents(root / "subagents")["count"] == 0


def test_a_symlink_loop_does_not_raise(root):
    """RuntimeError from resolve() must be contained, not surfaced."""
    missions = root / "missions"
    missions.mkdir()
    (missions / "a.json").symlink_to(missions / "b.json")
    (missions / "b.json").symlink_to(missions / "a.json")

    assert list_missions(missions) == []


def test_a_missing_directory_is_still_empty_not_an_error(root):
    assert list_missions(root / "nope") == []
    assert list_reports(root / "nope") == []
    assert list_hooks(root / "nope")["count"] == 0
    assert list_agents(root / "nope")["count"] == 0
    assert list_subagents(root / "nope")["count"] == 0


# --- the skip must be observable -------------------------------------------

def test_a_skipped_entry_is_logged(root, outside, caplog):
    """The issue asks for this explicitly: the helpers used to swallow errors
    silently, and an inventory that drops entries without a word is its own
    kind of wrong answer."""
    agents = root / "agents"
    agents.mkdir()
    (agents / "link.json").symlink_to(outside / "secret.json")

    with caplog.at_level(logging.WARNING, logger="arena.resources.listing"):
        list_agents(agents)

    assert any("resolves outside" in r.getMessage() for r in caplog.records), caplog.text


def test_a_broken_link_is_not_reported_as_an_escape(root, caplog):
    """A stale link is ordinary; only a real escape earns a warning.

    Found while sabotaging the fix: `strict=False` passed the whole suite,
    because an unresolvable path is dropped by `is_file()` anyway. The real
    difference the strict resolution makes is in what gets *said* -- a broken
    link pointing back inside the root was being logged as "resolves outside
    the resource root", which is untrue, and a log that cries escape at every
    stale link teaches the reader to ignore it.
    """
    agents = root / "agents"
    agents.mkdir()
    (agents / "stale.json").symlink_to(agents / "gone.json")

    with caplog.at_level(logging.DEBUG, logger="arena.resources.listing"):
        assert list_agents(agents)["count"] == 0

    warnings = [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert warnings == [], [r.getMessage() for r in warnings]
    assert any("no longer resolvable" in r.getMessage() for r in caplog.records), caplog.text


def test_an_entry_unlinked_mid_scan_is_survivable(root, monkeypatch):
    """`resolve(strict=True)` on a path that vanishes after `iterdir()`.

    The issue calls this out directly. It must be a skip, not a traceback.
    """
    import arena.resources.listing as mod

    agents = root / "agents"
    agents.mkdir()
    (agents / "a.json").write_text("{}", encoding="utf-8")
    (agents / "b.json").write_text("{}", encoding="utf-8")

    real_iterdir = Path.iterdir

    def vanishing(self):
        entries = list(real_iterdir(self))
        if self == agents:
            (agents / "a.json").unlink()
        return iter(entries)

    monkeypatch.setattr(Path, "iterdir", vanishing)
    result = mod.list_agents(agents)
    assert _names(result["agents"]) == ["b"]
