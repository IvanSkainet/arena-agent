"""One way to compute a mission's identifier (#354).

`str(item.get("id") or item.get("name") or "")` was written thirteen
times across the mission modules, and was not the same expression
thirteen times -- some copies stripped whitespace and some did not.
#350 was about one rule living in several places and those places
disagreeing; this is the same shape with a quieter symptom, so these
tests are about the disagreement, not about the helper.

The two behaviours below were reproduced against the code before the
fix, each next to a control that passed, so neither is a test written
to match an implementation that was already there.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from arena.resources.mission_family import get_mission_family
from arena.resources.mission_identifier import mission_item_id
from arena.resources.mission_lineage import get_mission_lineage


def _mission(root: Path, dirname: str, doc: dict) -> Path:
    directory = root / dirname
    directory.mkdir(parents=True)
    (directory / "mission.json").write_text(json.dumps(doc), encoding="utf-8")
    return directory


@pytest.mark.parametrize("stored_id", ["fam1", "fam 1 ", " fam1", "\tfam1\n"])
def test_a_mission_stays_in_its_own_family_whatever_pads_its_id(
        tmp_path: Path, stored_id: str) -> None:
    """A parent must appear in the family it is the root of.

    Before the fix `get_mission_family` stripped the root id and then
    compared unstripped ids against it, so a stored id with a trailing
    space matched nothing -- the root fell out of its own family while
    its child, which references the id as written, stayed in. The
    unpadded case is the control: it passed before the fix too, so a
    padded id failing was a real difference and not an empty walk.
    """
    _mission(tmp_path, "parent", {"id": stored_id, "title": "parent"})
    _mission(tmp_path, "kid", {
        "id": "kid-1",
        "lineage": {"parent_mission_id": stored_id,
                    "root_mission_id": stored_id, "depth": 1},
    })

    family = get_mission_family(tmp_path, "parent")

    assert family["ok"] is True
    assert sorted(m["name"] for m in family["members"]) == ["kid", "parent"]


@pytest.mark.parametrize("stored_id", ["P1", "P 1 "])
def test_a_child_is_found_whatever_pads_the_parent_id(
        tmp_path: Path, stored_id: str) -> None:
    """`mission_lineage` had the same split as the family view.

    It stripped the id it indexed parents by and did not strip the key
    it looked children up with, so the two halves of one lookup
    disagreed exactly when the id carried padding.
    """
    _mission(tmp_path, "p", {"id": stored_id, "title": "parent"})
    _mission(tmp_path, "c", {
        "id": "c1",
        "lineage": {"parent_mission_id": stored_id, "depth": 1},
    })

    lineage = get_mission_lineage(tmp_path, "p")

    assert [child["name"] for child in lineage["children"]] == ["c"]


def test_the_root_question_is_asked_by_name_not_by_argument_order(
        tmp_path: Path) -> None:
    """`prefer_root=True` means a different question, not a reordering.

    "Which family does this belong to" is not "what is this", and the
    family view needs the first. Spelling it as a keyword keeps the
    difference visible; as a reordered chain of `or`s it read exactly
    like the twelve other copies.
    """
    item = {"root_mission_id": " fam ", "id": "kid", "name": "kid-dir"}

    assert mission_item_id(item) == "kid"
    assert mission_item_id(item, prefer_root=True) == "fam"


def test_a_missing_id_falls_back_to_the_directory_name() -> None:
    """The fallback chain still behaves, including when a key is blank.

    A present-but-empty `id` must not win over `name` -- `or` already
    did that, and the helper must not quietly become `if "id" in item`.
    """
    assert mission_item_id({"id": "", "name": "dir"}) == "dir"
    assert mission_item_id({"id": None, "name": "dir"}) == "dir"
    assert mission_item_id({"id": "   ", "name": "dir"}) == "dir"
    assert mission_item_id({}) == ""


def test_no_module_grows_a_fourteenth_copy_of_the_identifier() -> None:
    """The test that fails when the expression is written out again.

    Same guard as `test_every_mission_walk_uses_the_shared_one` in
    #350: consolidating is worth little if the next edit adds copy
    fourteen, because that copy will strip or not strip on its own.
    """
    resources = Path(__file__).resolve().parents[1] / "arena" / "resources"
    pattern = re.compile(r'get\(\s*"id"\s*\)\s*or\s*\w+\.get\(\s*"name"\s*\)')

    offenders = {
        path.name
        for path in resources.glob("*.py")
        if path.name != "mission_identifier.py" and pattern.search(
            path.read_text(encoding="utf-8"))
    }

    assert offenders == set(), (
        f"these modules compute a mission id themselves instead of calling "
        f"mission_item_id: {sorted(offenders)}")


def test_the_grep_guard_would_notice_a_copy() -> None:
    """The control for the test above, which passes on a broken regex.

    "No module matches" is satisfied by a pattern that matches nothing
    at all, so the pattern is checked against the text it exists to
    find. Without this the guard could rot silently -- the failure mode
    #350 kept hitting.
    """
    pattern = re.compile(r'get\(\s*"id"\s*\)\s*or\s*\w+\.get\(\s*"name"\s*\)')

    assert pattern.search('str(item.get("id") or item.get("name") or "")')
    assert pattern.search('str(current.get("id") or current.get("name"))')
    assert not pattern.search("mission_item_id(item)")
