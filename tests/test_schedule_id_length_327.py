"""A schedule id the filesystem refuses is a 400, not a 500 (#327).

Schemathesis found this on an unrelated PR: a generated schedule id of
combining marks -- 252 characters, 432 UTF-8 bytes -- walked past the
traversal guard in `_schedule_path`, reached `write_text`, and came back
as `OSError: [Errno 36] File name too long` wrapped in a 500.

The character count is what makes it a real bug rather than a fuzzer
curiosity. 252 characters looks harmless next to a 255 limit; the limit
is in bytes, and combining marks cost two or three each. So the test
measures in bytes too, and a fix that clamps `len(name)` fails it.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from arena.resources.mission_schedule_store import (
    _schedule_path,
    delete_schedule_def,
    save_schedule_def,
)

# 147 characters, 252 bytes -- 257 with the `.json` suffix. Sized so that
# a character count of the whole filename stays under 255 while the byte
# count goes over it: a fix that clamps `len(name)` lets this through and
# still hits the OSError. The fuzzer's own id was longer and happened to
# be over both limits, which would have let a character-based fix look
# correct.
_COMBINING_ID = "T\u033a\u033a\u0315o\u035e i\u0332\u032c\u0347\u032a\u0359n\u031d\u0317\u0355v\u031f\u031c\u0318" * 7


def test_the_id_from_the_fuzzer_is_short_in_characters_and_long_in_bytes():
    """Guard the fixture itself: it has to be the shape being tested.

    Both assertions are about the filename, suffix included, because that
    is the component the filesystem measures. If either stops holding,
    the tests below still pass while no longer distinguishing a byte-aware
    fix from a character-based one.
    """
    filename = f"{_COMBINING_ID}.json"
    assert len(filename) < 255, "a character count would now catch it too"
    assert len(filename.encode("utf-8")) > 255, "no longer over the byte limit"


def test_saving_an_over_long_schedule_id_answers_400(tmp_path: Path):
    result = save_schedule_def(
        tmp_path,
        {"schedule_id": _COMBINING_ID, "mission_id": "m", "action": "run",
         "every_minutes": 10},
    )
    assert result["ok"] is False
    assert result["status"] == 400, "the filesystem's refusal reached the client as a 500"
    assert "too long" in result["error"]


def test_deleting_an_over_long_schedule_id_answers_400(tmp_path: Path):
    result = delete_schedule_def(tmp_path, _COMBINING_ID)
    assert result["ok"] is False
    assert result["status"] == 400


def test_nothing_is_written_when_the_id_is_refused(tmp_path: Path):
    """A refusal that still touched the disk would be the worse failure."""
    save_schedule_def(
        tmp_path,
        {"schedule_id": _COMBINING_ID, "mission_id": "m", "action": "run",
         "every_minutes": 10},
    )
    assert list(tmp_path.rglob("*.json")) == []


def test_the_suffix_counts_toward_the_limit(tmp_path: Path):
    """`.json` is part of the component the filesystem measures.

    An id sized to land in the five bytes between the limit and the limit
    plus the suffix passes a check on the bare id and fails on the path
    that gets written. Asking about the filename closes that gap.
    """
    from arena.resources.mission_identifier import NAME_MAX_UNITS

    exact = "a" * NAME_MAX_UNITS
    assert len(exact.encode("utf-8")) == NAME_MAX_UNITS
    with pytest.raises(ValueError, match="too long"):
        _schedule_path(tmp_path, exact)


def test_an_ordinary_id_still_saves_and_deletes(tmp_path: Path):
    """The tripwire: a gate that refuses everything also passes the above."""
    saved = save_schedule_def(
        tmp_path,
        {"schedule_id": "daily-run", "mission_id": "m", "action": "run",
         "every_minutes": 10},
    )
    assert saved["ok"] is True
    written = tmp_path / "daily-run.json"
    assert written.exists()
    assert json.loads(written.read_text(encoding="utf-8"))["id"] == "daily-run"
    assert delete_schedule_def(tmp_path, "daily-run")["ok"] is True
