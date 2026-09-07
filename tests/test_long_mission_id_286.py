"""A mission id longer than a filename is refused, not answered with a 500 (#286).

Found by the #258 fuzzing gate while the second batch of checks was being
prepared: `POST /v1/mission/rerun` with a 40-character id built out of
combining marks -- 1.6 kB once encoded -- answered 500. The filesystem's
own refusal, `OSError: [Errno 36] File name too long`, came out of
`Path.exists()`, which is not a place any caller expects an exception.

Same shape as #280, so the same two halves: the reader refuses the lookup
before touching the disk, and the writer refuses to create a directory the
filesystem cannot hold. The limit is 255 *bytes* per path component on
ext4, APFS and NTFS alike, which is why the id that found this is only 40
characters long.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from arena.resources.mission_family import get_mission_family
from arena.resources.mission_identifier import NAME_MAX_BYTES, too_long_for_disk
from arena.resources.mission_lineage import get_mission_lineage
from arena.resources.mission_state import (
    get_mission_history,
    get_mission_report,
    get_mission_status,
)
from arena.resources.missions_manage import create_mission_from_draft

# One ASCII, one that is short in characters and long in bytes -- the second
# is the shape the fuzzer actually found, and a character-counting guard
# would let it straight through.
TOO_LONG = (
    "a" * (NAME_MAX_BYTES + 1),
    "Ṱ̺̺̕o͞ ̷i̲̬͇̪͙n̝̗͕v̟̜̘̦͟o̶̙̰̠kè͚̮̺̪̹̱̤ ̖t̝͕̳̣̻̪͞h̼͓̲̦̳̘̲e͇̣̰̦̬͎ ̢̼̻̱̘h͚͎͙̜̣̲ͅi̦̲̣̰̤v̻͍e̺̭̳̪̰-m̢iͅn̖̺̞̲̯̰d̵̼̟͙̩̼̘̳" * 2,
    "\U0001f600" * 64,
)

READERS = (
    get_mission_status,
    get_mission_history,
    get_mission_report,
    get_mission_lineage,
    get_mission_family,
)


@pytest.mark.parametrize("reader", READERS, ids=lambda f: f.__name__)
@pytest.mark.parametrize("name", TOO_LONG, ids=("ascii", "combining", "emoji"))
def test_reading_an_over_long_mission_id_is_a_400(
        tmp_path: Path, reader, name: str) -> None:
    """Every mission read funnels through `mission_dir`, so every one is covered."""
    result = reader(tmp_path, name)
    assert result["ok"] is False
    assert result["status"] == 400, result
    assert "too long" in result["error"]


@pytest.mark.parametrize("name", TOO_LONG, ids=("ascii", "combining", "emoji"))
def test_creating_an_over_long_mission_id_is_a_400(tmp_path: Path, name: str) -> None:
    """The writer half: `mkdir` would raise ENAMETOOLONG, so it is never called."""
    result = create_mission_from_draft(
        missions_dir=tmp_path, draft={"title": "t"}, mission_id=name)
    assert result["ok"] is False
    assert result["status"] == 400, result
    assert "too long" in result["error"]
    assert list(tmp_path.iterdir()) == []


def test_a_name_at_the_limit_is_still_allowed(tmp_path: Path) -> None:
    """255 bytes is a legal filename, and the guard stops one byte later.

    An off-by-one here would be invisible in normal use and would refuse
    ids that work, so the boundary is asserted from both sides.
    """
    at_limit = "a" * NAME_MAX_BYTES
    assert too_long_for_disk(at_limit) is False
    assert too_long_for_disk(at_limit + "a") is True

    created = create_mission_from_draft(
        missions_dir=tmp_path, draft={"title": "t"}, mission_id=at_limit)
    assert created["ok"] is True
    assert (tmp_path / at_limit).is_dir()
    assert get_mission_status(tmp_path, at_limit)["ok"] is True


def test_the_limit_is_bytes_not_characters(tmp_path: Path) -> None:
    """A 100-character id can be 400 bytes, and that is the case that broke."""
    wide = "\U0001f600" * 100  # 4 bytes each
    assert len(wide) < NAME_MAX_BYTES
    assert too_long_for_disk(wide) is True


def test_a_lone_surrogate_is_measured_rather_than_raising() -> None:
    """A JSON body can carry lone surrogates; measuring one must not throw.

    `"\\udb72"` reaches the handler as a real string, and `str.encode()`
    without `surrogatepass` raises `UnicodeEncodeError` -- which would swap
    one 500 for another.
    """
    assert too_long_for_disk("m\udb72\udc05x") is False
    assert too_long_for_disk("\udb72" * 256) is True
