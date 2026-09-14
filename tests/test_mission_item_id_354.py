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

import ast
import json
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


def test_two_ids_that_differ_only_by_padding_do_not_overwrite_each_other(
        tmp_path: Path, caplog) -> None:
    """Stripping made a collision reachable that verbatim ids could not.

    Before this PR two directories had to store the very same string to
    share an index key. Once ids are stripped, `"dup"` and `" dup "`
    collide -- and a plain dict comprehension would answer with
    whichever was walked last, silently. Review caught it; checked
    against master, which returns `dirA`, so this is the behaviour
    being preserved rather than a new rule.

    Resolving the clash is not this code's business -- two missions
    claiming one id is a fact about the stored data -- so the first
    walked wins deterministically and the loser is logged.
    """
    for dirname, stored in (("dirA", "dup"), ("dirB", " dup ")):
        _mission(tmp_path, dirname, {"id": stored, "title": dirname})
    _mission(tmp_path, "kid", {
        "id": "k", "lineage": {"parent_mission_id": "dup", "depth": 1}})

    with caplog.at_level("WARNING"):
        lineage = get_mission_lineage(tmp_path, "kid")

    assert [a["name"] for a in lineage["ancestors"]] == ["dirA"]
    assert any("dup" in r.getMessage() for r in caplog.records
               if r.levelname == "WARNING"), (
        "a collision between two stored ids was resolved without a word")


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


def _modules_computing_an_id_themselves(resources: Path) -> set[str]:
    """Modules containing `X.get(<id>) or Y.get(<name>)`, found by AST.

    The first version of this guard was a regex over the source text,
    and review pointed out it only recognised double-quoted keys: the
    same expression with `'id'` would slip past and the test would
    still be green while the invariant it names was broken. A guard
    that can be defeated by a quote character is worse than none,
    because it reads like coverage.

    Parsing removes the spelling question entirely -- quotes, spacing
    and line breaks are gone by the time the tree exists, so there is
    one thing to recognise instead of a list of ways to write it.
    """
    def _is_get_of(node: ast.AST, key: str) -> bool:
        return (isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "get"
                and len(node.args) == 1
                and isinstance(node.args[0], ast.Constant)
                and node.args[0].value == key)

    def _mentions(node: ast.AST, key: str) -> bool:
        return any(_is_get_of(child, key) for child in ast.walk(node))

    def _is_label_chain(node: ast.AST) -> bool:
        # `title or name or id` is a different question -- the most
        # human-readable label, not the identifier -- and it is
        # deliberately unstripped because it goes into prose, not into
        # a dict key. Recognised by the first operand so the guard does
        # not drag `mission_recovery` in and teach the next person to
        # widen the allowlist instead of reading it.
        return (isinstance(node, ast.BoolOp) and isinstance(node.op, ast.Or)
                and _is_get_of(node.values[0], "title"))

    offenders = set()
    for path in sorted(resources.glob("*.py")):
        if path.name == "mission_identifier.py":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if (isinstance(node, ast.BoolOp) and isinstance(node.op, ast.Or)
                    and _mentions(node, "id") and _mentions(node, "name")
                    # A chain can be nested inside an f-string, in which
                    # case the outer `or` is not the label chain but
                    # contains it and nothing else that computes an id.
                    and not any(_is_label_chain(c) for c in ast.walk(node))):
                offenders.add(path.name)
    return offenders


def test_no_module_grows_a_thirteenth_copy_of_the_identifier() -> None:
    """The test that fails when the expression is written out again.

    Same guard as `test_every_mission_walk_uses_the_shared_one` in
    #350: consolidating is worth little if the next edit adds copy
    thirteen, because that copy will strip or not strip on its own.
    """
    resources = Path(__file__).resolve().parents[1] / "arena" / "resources"

    assert _modules_computing_an_id_themselves(resources) == set(), (
        "these modules compute a mission id themselves instead of calling "
        f"mission_item_id: {sorted(_modules_computing_an_id_themselves(resources))}")


@pytest.mark.parametrize("spelling", [
    'str(item.get("id") or item.get("name") or "")',
    "str(item.get('id') or item.get('name'))",
    'str(\n    item.get("id")\n    or item.get("name")\n)',
    'x = item.get("id") or other.get("name") or fallback',
])
def test_the_guard_notices_a_copy_however_it_is_spelled(
        tmp_path: Path, spelling: str) -> None:
    """The control for the test above, which passes on a blind guard.

    "No module matches" is also satisfied by a check that matches
    nothing at all, so the check is run against the text it exists to
    find -- including the single-quoted form that defeated the regex
    this replaced.
    """
    resources = tmp_path / "resources"
    resources.mkdir()
    (resources / "offender.py").write_text(spelling + "\n", encoding="utf-8")

    assert _modules_computing_an_id_themselves(resources) == {"offender.py"}


def test_the_guard_leaves_the_human_readable_label_alone(tmp_path: Path) -> None:
    """`title or name or id` asks for a label, not an identifier.

    It is deliberately unstripped -- the value goes into prose, not
    into a dict key -- so folding it into the helper would change
    behaviour for no reason. The exemption is keyed on `title` coming
    first rather than on a module allowlist, which would otherwise be
    the thing that quietly grows.
    """
    resources = tmp_path / "resources"
    resources.mkdir()
    (resources / "label.py").write_text(
        'title = m.get("title") or m.get("name") or m.get("id") or "mission"\n',
        encoding="utf-8")

    assert _modules_computing_an_id_themselves(resources) == set()


def test_the_guard_does_not_fire_on_the_shared_helper(tmp_path: Path) -> None:
    """And the other half of the control: a converted call is clean.

    Without this the guard could be a function that returns every
    module it is shown, which would also make the real test green
    once -- and red forever after for the wrong reason.
    """
    resources = tmp_path / "resources"
    resources.mkdir()
    (resources / "clean.py").write_text(
        "key = mission_item_id(item)\nother = item.get('id')\n", encoding="utf-8")

    assert _modules_computing_an_id_themselves(resources) == set()
