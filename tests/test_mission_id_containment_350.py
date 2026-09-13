"""A mission id must name one directory inside the missions directory.

#350: `mission_dir` refused `..`, path separators and a leading dot from
the day it was written, while `create_mission_from_draft` refused
nothing. So `mission_id="../../secrets"` wrote `mission.json` and
`PLAN.md` outside `missions_dir`, over whatever was already there, and
answered `ok: True`.

Two separate defects came out of the same gap, which is why the tests
below check both directions:

* writing outside the root at all;
* writing a mission the reader then cannot open -- `_slug` kept dot
  runs, so a title of `Ship v2..final` produced an id containing `..`,
  created successfully and afterwards unreadable and unlistable.

The through-line is that two pieces of code held two opinions about the
same string. `test_the_writer_and_the_reader_agree` is the one that
would have caught it, and the one that keeps them from drifting again.
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

import pytest

from arena.resources.mission_catalog import mission_dir
from arena.resources.mission_identifier import (
    escapes_the_root,
    not_a_single_directory_name,
)
from arena.resources.missions_manage import _slug, create_mission_from_draft

# Names that navigate somewhere other than "one directory below the
# root". `sub/../ok` is here deliberately: it resolves back inside, so
# containment alone would allow it, but it is still not a plain name
# and the reader has always refused it.
NAVIGATING_NAMES = [
    "../escaped",
    "../../secrets",
    "a/b",
    "a\\b",
    ".hidden",
    "..",
    ".",
    "a..b",
    "sub/../ok",
]

PLAIN_NAMES = [
    "ok-name",
    "scenario-armed-posture-live-proof-41470",
    "20260913T102117Z-mission-7d0de8",
    "with.dot",
]


@pytest.fixture
def missions_dir(tmp_path: Path) -> Path:
    directory = tmp_path / "missions"
    directory.mkdir()
    return directory


def _create(missions_dir: Path, mission_id: str) -> dict:
    return create_mission_from_draft(
        missions_dir=missions_dir,
        draft={"title": "t", "goal": "g"},
        mission_id=mission_id,
        overwrite=True,
    )


def test_a_relative_path_does_not_write_outside_the_root(tmp_path):
    """The original report, end to end.

    A pre-existing `mission.json` outside the root must survive, and
    the call must not claim success.
    """
    missions = tmp_path / "agent" / "missions"
    missions.mkdir(parents=True)
    victim = tmp_path / "secrets"
    victim.mkdir()
    (victim / "mission.json").write_text("ORIGINAL", encoding="utf-8")

    result = _create(missions, "../../secrets")

    assert result["ok"] is False
    assert result["status"] == 400
    assert (victim / "mission.json").read_text(encoding="utf-8") == "ORIGINAL"


@pytest.mark.parametrize("mission_id", NAVIGATING_NAMES)
def test_a_navigating_name_is_refused_with_400(missions_dir, mission_id):
    """Every name the reader rejects, the writer now rejects too."""
    result = _create(missions_dir, mission_id)

    assert result["ok"] is False
    assert result["status"] == 400


@pytest.mark.parametrize("mission_id", PLAIN_NAMES)
def test_a_plain_name_is_still_accepted(missions_dir, mission_id):
    """The refusal must not swallow the names the product uses.

    `scenario-` prefixed ids and the generated `<stamp>-<slug>-<hex>`
    shape both have to keep working, and a single dot is legal in a
    directory name.
    """
    result = _create(missions_dir, mission_id)

    assert result["ok"] is True
    assert (missions_dir / mission_id / "mission.json").exists()


@pytest.mark.parametrize("mission_id", NAVIGATING_NAMES + PLAIN_NAMES)
def test_the_writer_and_the_reader_agree(missions_dir, mission_id):
    """Neither side may accept a name the other refuses.

    This is the property that was missing. The two had drifted apart
    with no test relating them, so the writer could create a mission
    the reader could not open and nothing noticed.
    """
    written = _create(missions_dir, mission_id)
    try:
        mission_dir(missions_dir, mission_id)
        readable = True
    except ValueError:
        readable = False

    assert bool(written["ok"]) == readable, (
        f"{mission_id!r}: writer "
        f"{'accepted' if written['ok'] else 'refused'} it, reader "
        f"{'accepted' if readable else 'refused'} it"
    )


@pytest.mark.skipif(
    not hasattr(os, "symlink"),
    reason="platform has no symlinks to plant",
)
def test_a_symlinked_child_does_not_escape(tmp_path):
    """A plain name can still land outside, via a link in the root.

    No `..` and no separator here, so the string check sees nothing
    wrong; only resolving the path does. Same reasoning as
    `arena/resources/listing.py` for #120.
    """
    missions = tmp_path / "missions"
    missions.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    try:
        os.symlink(outside, missions / "plain", target_is_directory=True)
    except (OSError, NotImplementedError):  # pragma: no cover - Windows ACL
        pytest.skip("cannot create a directory symlink on this machine")

    result = _create(missions, "plain")

    assert result["ok"] is False
    assert result["status"] == 400
    assert not (outside / "mission.json").exists()


@pytest.mark.parametrize("title", [
    "Ship v2..final",
    "...",
    ".hidden start",
    "a/b",
    "  ..  ",
])
def test_a_generated_id_is_one_the_reader_accepts(missions_dir, title):
    """The writer must not invent a name it would refuse from a caller.

    `_slug` kept dot runs, so an ordinary title produced an id with
    `..` in it: created, then unreadable and absent from listings. No
    attacker involved -- a punctuation choice in a title was enough.
    """
    result = create_mission_from_draft(
        missions_dir=missions_dir,
        draft={"title": title, "goal": "g"},
    )

    assert result["ok"] is True
    generated = result["mission_id"]
    assert not_a_single_directory_name(generated) is None, (
        f"title {title!r} generated {generated!r}, which the reader "
        "refuses"
    )
    assert mission_dir(missions_dir, generated).exists()


def test_the_slug_collapses_dot_runs():
    """The fragment itself, without going through the filesystem."""
    assert _slug("Ship v2..final") == "ship-v2.final"
    assert _slug("...") == "mission"


@pytest.mark.parametrize(("name", "fragment"), [
    ("a/b", "path separator"),
    ("a\\b", "path separator"),
    ("a..b", ".."),
    (".hidden", "dot"),
    ("", "empty"),
])
def test_the_refusal_says_which_rule_was_broken(name, fragment):
    """A caller has to be able to fix the name from the message."""
    reason = not_a_single_directory_name(name, label="mission id")

    assert reason is not None
    assert fragment in reason
    assert "mission id" in reason


def test_a_usable_name_passes_the_check():
    assert not_a_single_directory_name("ok-name", label="mission id") is None


def test_the_check_is_reachable_from_a_long_temp_root():
    """Containment must not trip over an ordinary deep path.

    `tempfile` on macOS hands back `/var/...`, a symlink to
    `/private/var`, so a naive comparison of unresolved paths reports an
    escape for a perfectly normal directory. Resolving both sides is
    what avoids that, and this keeps the check honest on the runner
    where it matters.
    """
    with tempfile.TemporaryDirectory() as raw:
        missions = Path(raw) / "missions"
        missions.mkdir()

        result = _create(missions, "ok-name")

    assert result["ok"] is True


def test_the_module_imports_cleanly():
    """Guards against a circular import between the two modules.

    The shared function lives in `mission_identifier`, which
    `missions_manage` and `mission_catalog` both import; a cycle here
    would surface as an ImportError only on a cold interpreter.
    """
    assert "arena.resources.mission_identifier" in sys.modules


# --------------------------------------------------------------------
# Symlinks. Raised in review by sourcery, coderabbit and cubic
# independently: the first revision closed the writer and left every
# reader open, and treated "contained" as sufficient when an alias
# *inside* the root can still land on another mission's files.

@pytest.fixture
def linked_tree(tmp_path: Path):
    """A missions root holding both kinds of dangerous alias."""
    missions = tmp_path / "missions"
    missions.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "mission.json").write_text('{"id": "stolen"}', encoding="utf-8")
    real = missions / "real"
    real.mkdir()
    (real / "mission.json").write_text("ORIGINAL", encoding="utf-8")
    try:
        os.symlink(outside, missions / "out", target_is_directory=True)
        os.symlink(real, missions / "alias", target_is_directory=True)
    except (OSError, NotImplementedError):  # pragma: no cover - Windows ACL
        pytest.skip("cannot create a directory symlink on this machine")
    return missions, outside, real


def test_a_reader_does_not_follow_a_link_out_of_the_root(linked_tree):
    """`mission_dir` validated the string and returned the path unread.

    Every mission read funnels through it -- status, report, history,
    lineage, family, show -- so a single planted link served an
    external `mission.json` to all of them.
    """
    missions, _outside, _real = linked_tree

    with pytest.raises(ValueError, match="escapes"):
        mission_dir(missions, "out")


def test_a_writer_does_not_follow_a_link_out_of_the_root(linked_tree):
    missions, outside, _real = linked_tree

    result = _create(missions, "out")

    assert result["ok"] is False
    assert result["status"] == 400
    assert (outside / "mission.json").read_text(encoding="utf-8") == '{"id": "stolen"}'


def test_an_alias_onto_another_mission_is_refused(linked_tree):
    """Containment alone is not enough.

    `missions/alias -> missions/real` resolves *inside* the root, so an
    `is_relative_to` test passes it, and `overwrite=True` then rewrites
    the other mission's `mission.json` and `PLAN.md` through the alias.
    """
    missions, _outside, real = linked_tree

    result = _create(missions, "alias")

    assert result["ok"] is False
    assert result["status"] == 400
    assert (real / "mission.json").read_text(encoding="utf-8") == "ORIGINAL"


def test_a_reader_refuses_the_in_root_alias_too(linked_tree):
    """Writer and reader stay in step on links, as they now do on names."""
    missions, _outside, _real = linked_tree

    with pytest.raises(ValueError, match="escapes"):
        mission_dir(missions, "alias")


def test_a_real_directory_is_not_an_escape(tmp_path):
    """The link check must not refuse ordinary missions."""
    missions = tmp_path / "missions"
    (missions / "plain").mkdir(parents=True)

    assert escapes_the_root(missions / "plain", missions) is False


def test_a_path_that_does_not_exist_yet_is_not_an_escape(tmp_path):
    """Creation asks before the directory exists; that is not a failure."""
    missions = tmp_path / "missions"
    missions.mkdir()

    assert escapes_the_root(missions / "not-created-yet", missions) is False


@pytest.mark.parametrize("blow_up", [OSError, RuntimeError, ValueError])
def test_a_resolution_failure_fails_closed(tmp_path, monkeypatch, blow_up):
    """Whatever `resolve()` raises, the answer is "escapes", not a 500.

    Version-dependent, which is why this injects the exception instead
    of building the condition: a symlink loop surfaces as `OSError` on
    3.13 and `RuntimeError` on 3.10-3.12, and both are in the CI
    matrix. Constructing a real loop would exercise only whichever
    interpreter happens to be running -- and in fact could not reach
    the handler at all on 3.13, where `is_symlink()` answers first.
    """
    missions = tmp_path / "missions"
    missions.mkdir()

    def refuse(*_args, **_kwargs):
        raise blow_up("resolution failed")

    monkeypatch.setattr(Path, "resolve", refuse)

    assert escapes_the_root(missions / "anything", missions) is True


def test_a_symlink_loop_fails_closed(tmp_path):
    """The real condition, on whatever interpreter is running."""
    missions = tmp_path / "missions"
    missions.mkdir()
    first = missions / "first"
    second = missions / "second"
    try:
        os.symlink(second, first)
        os.symlink(first, second)
    except (OSError, NotImplementedError):  # pragma: no cover - Windows ACL
        pytest.skip("cannot create a symlink on this machine")

    assert escapes_the_root(first, missions) is True

    result = _create(missions, "first")
    assert result["ok"] is False
    assert result["status"] == 400


def test_the_pre_stat_guard_uses_the_shared_rule():
    """`_looks_unsafe` was a second copy of the same predicate.

    It gates the `.exists()` probes inside `resolve_mission_name`, so
    if the two drifted, resolution would stat a name the writer and the
    reader both reject. It now delegates.
    """
    from arena.resources import mission_identifier

    for name in NAVIGATING_NAMES:
        assert mission_identifier._looks_unsafe(name) is True
    for name in PLAIN_NAMES:
        assert mission_identifier._looks_unsafe(name) is False
