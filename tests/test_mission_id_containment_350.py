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
from arena.resources.mission_identifier import not_a_single_directory_name
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
