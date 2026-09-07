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

import os
from pathlib import Path

import pytest

from arena.resources.listing import show_mission
from arena.resources.mission_family import get_mission_family
from arena.resources.mission_identifier import (
    NAME_MAX_UNITS,
    unusable_directory_name,
)
from arena.resources.mission_lineage import get_mission_lineage
from arena.resources.mission_state import (
    get_mission_history,
    get_mission_report,
    get_mission_status,
)
from arena.resources.missions_manage import create_mission_from_draft

# One ASCII, one that is short in characters and long in bytes -- the second
# is the shape the fuzzer actually found, and a character-counting guard
# would let it straight through. Each of the three is over the limit in
# *both* units, so the parametrisation reads the same on ext4 and on NTFS;
# the byte/unit difference has a test of its own at the bottom.
TOO_LONG = (
    "a" * (NAME_MAX_UNITS + 1),
    "Ṱ̺̺̕o͞ ̷i̲̬͇̪͙n̝̗͕v̟̜̘̦͟o̶̙̰̠kè͚̮̺̪̹̱̤ ̖t̝͕̳̣̻̪͞h̼͓̲̦̳̘̲e͇̣̰̦̬͎ ̢̼̻̱̘h͚͎͙̜̣̲ͅi̦̲̣̰̤v̻͍e̺̭̳̪̰-m̢iͅn̖̺̞̲̯̰d̵̼̟͙̩̼̘̳" * 3,
    "\U0001f600" * 128,
)

READERS = (
    get_mission_status,
    get_mission_history,
    get_mission_report,
    get_mission_lineage,
    get_mission_family,
    # Predates `mission_dir` and does its own lookup, which is exactly how
    # it missed the guard the first time round (cubic, sourcery).
    show_mission,
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
    at_limit = "a" * NAME_MAX_UNITS
    assert unusable_directory_name(at_limit) is None
    assert unusable_directory_name(at_limit + "a") is not None

    created = create_mission_from_draft(
        missions_dir=tmp_path, draft={"title": "t"}, mission_id=at_limit)
    assert created["ok"] is True
    assert (tmp_path / at_limit).is_dir()
    assert get_mission_status(tmp_path, at_limit)["ok"] is True


def test_the_limit_is_not_counted_in_characters(tmp_path: Path) -> None:
    """A 200-character id can be 800 bytes, and that is the case that broke.

    The unit is the local filesystem's: bytes of UTF-8 on ext4 and APFS,
    UTF-16 code units on NTFS. Counting characters would let the id that
    found this straight through on either.
    """
    wide = "\U0001f600" * 200
    assert len(wide) < NAME_MAX_UNITS
    assert unusable_directory_name(wide) is not None


@pytest.mark.parametrize("name", ["m\x00x", "\x00", "mission\x00.json"])
def test_a_nul_is_refused_rather_than_reaching_mkdir(tmp_path: Path, name: str) -> None:
    """`mkdir` answers a NUL with `ValueError`, which left as a 500 (cubic)."""
    assert unusable_directory_name(name) is not None
    created = create_mission_from_draft(
        missions_dir=tmp_path, draft={"title": "t"}, mission_id=name)
    assert created["status"] == 400
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("name", ["m\udb72x", "\udc05", "\udb72" * 3])
def test_an_unpaired_surrogate_is_refused(tmp_path: Path, name: str) -> None:
    """Short enough to pass a length check, fatal at `fsencode`.

    A JSON body can carry a lone surrogate, and encoding one for the
    filesystem raises `UnicodeEncodeError` -- the same 500 by another
    route, which is why the guard is about the characters and not only
    the length (sourcery, cubic).
    """
    assert unusable_directory_name(name) is not None
    created = create_mission_from_draft(
        missions_dir=tmp_path, draft={"title": "t"}, mission_id=name)
    assert created["status"] == 400
    assert get_mission_status(tmp_path, name)["status"] == 400
    assert list(tmp_path.iterdir()) == []


def test_the_unit_follows_the_local_filesystem() -> None:
    """NTFS counts UTF-16 code units, ext4 counts bytes; 64 emoji differ.

    256 bytes and 128 units: refused on Linux, legal on Windows. Refusing
    it everywhere would have the bridge turn down ids its own filesystem
    would accept (cubic).
    """
    emoji = "\U0001f600" * 64
    refused = unusable_directory_name(emoji) is not None
    assert refused is (os.name != "nt")
