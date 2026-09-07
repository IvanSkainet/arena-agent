"""A mission id made of whitespace is refused, not answered with a 500 (#280).

Found by the #258 fuzzing gate on its first run in CI:
`GET /v1/mission/family?mission_id=%C2%85` answered
`500 {"error": "family root unavailable"}`. U+0085 is a line separator, and
`str.strip()` treats it as whitespace, so a mission created under that name
read its own id back as empty and the family lookup gave up with a server
error for a request that was well formed.

Two halves, because either alone leaves the other reachable: the writer
refuses to create a mission nothing can address afterwards, and the reader
answers 404 for one that already exists.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from arena.resources.mission_family import get_mission_family
from arena.resources.missions_manage import create_mission_from_draft

BLANK_IDS = ("\u0085", " ", "\t", "\u00a0", "\u2028", "  \n ")


@pytest.mark.parametrize("blank", BLANK_IDS)
def test_a_mission_id_of_whitespace_is_refused(tmp_path: Path, blank: str) -> None:
    """The writer half: nothing addressable, so nothing written."""
    result = create_mission_from_draft(
        missions_dir=tmp_path, draft={"title": "t"}, mission_id=blank)
    assert result["ok"] is False
    assert result["status"] == 400
    assert list(tmp_path.iterdir()) == []


def test_a_real_id_still_creates_a_mission(tmp_path: Path) -> None:
    """The refusal is about blankness, not about unusual characters.

    `Ünïcödé-миссия` is a perfectly good directory name; the guard must not
    turn into a general-purpose filter that quietly narrows what callers
    may name things.
    """
    result = create_mission_from_draft(
        missions_dir=tmp_path, draft={"title": "t"}, mission_id="Ünïcödé-миссия")
    assert result["ok"] is True
    assert (tmp_path / "Ünïcödé-миссия" / "mission.json").exists()


def test_reading_a_family_whose_id_is_blank_is_a_404(tmp_path: Path) -> None:
    """The reader half, for missions written before the guard existed.

    Built by hand rather than through the writer, which now refuses: the
    point is a directory that is already on disk, which is exactly the state
    the fuzzer reached in CI.
    """
    mission = tmp_path / "\u0085"
    (mission / "logs").mkdir(parents=True)
    (mission / "mission.json").write_text(
        json.dumps({"id": "\u0085", "title": "t", "runs": []}), encoding="utf-8")

    result = get_mission_family(tmp_path, "\u0085")

    assert result["ok"] is False
    assert result["status"] == 404
    assert "no usable id" in result["error"]
