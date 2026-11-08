"""Facts appended to `facts.jsonl` after the first import must still arrive.

`scripts/agent_helpers.py put` is a live writer of `memory/facts.jsonl`, and the
importer used to be one-shot: it read the file, renamed it to
`facts.jsonl.migrated`, and returned early on every later start. From then on
the script answered `ok` for facts that `GET /v1/memory` could never see, with
no signal anywhere -- the same "reported success, did nothing" shape as the
rest of the audit, but with data loss attached.

Reproduced on a live bridge (2026-11-07 durability round):

    empty home, first start          -> memory/facts.db, no facts.jsonl
    agent_helpers.py put k1 v1  ok   -> facts.jsonl appears
    restart                          -> API sees k1, file renamed .migrated
    agent_helpers.py put k2 v2  ok   -> a second facts.jsonl appears
    restart                          -> API sees only k1. k2 never arrives.

The importer now keeps a byte offset next to the file and reads only what is
new, so the legacy file and the live writer share one destination.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

from arena.memory.schema import init_memory_db

FACT = '{{"key": "{key}", "value": "{value}", "timestamp": "2026-11-07T00:00:00+00:00"}}'


def _home(tmp_path: Path) -> tuple[Path, Path]:
    db = tmp_path / "memory" / "facts.db"
    jsonl = tmp_path / "memory" / "facts.jsonl"
    db.parent.mkdir(parents=True, exist_ok=True)
    return db, jsonl


def _restart(db: Path, jsonl: Path) -> None:
    """One bridge start, from the memory layer's point of view."""
    init_memory_db(db_path=db, jsonl_path=jsonl)


def _append(jsonl: Path, *pairs: tuple[str, str], newline: bool = True) -> None:
    body = "".join(FACT.format(key=k, value=v) + ("\n" if newline else "") for k, v in pairs)
    with jsonl.open("a", encoding="utf-8") as handle:
        handle.write(body)


def _keys(db: Path) -> dict[str, str]:
    with sqlite3.connect(db) as conn:
        return {row[0]: row[1] for row in conn.execute(
            "SELECT key, value FROM memory_facts WHERE profile='default'"
        ).fetchall()}


def test_a_fact_written_after_the_first_import_still_arrives(tmp_path):
    """The finding, end to end, in the order the live reproduction used."""
    db, jsonl = _home(tmp_path)
    _append(jsonl, ("k1", "v1"))
    _restart(db, jsonl)
    assert _keys(db) == {"k1": "v1"}

    _append(jsonl, ("k2", "v2"))
    _restart(db, jsonl)

    assert _keys(db) == {"k1": "v1", "k2": "v2"}, (
        "a fact appended after the first import never reached the database"
    )


def test_the_legacy_migrated_file_does_not_block_later_authors(tmp_path):
    """The old sentinel marked "done forever"; it must not outlive its meaning."""
    db, jsonl = _home(tmp_path)
    _append(jsonl, ("k1", "v1"))
    _restart(db, jsonl)
    (jsonl.parent / "facts.jsonl.migrated").write_text(
        FACT.format(key="k1", value="v1") + "\n", encoding="utf-8"
    )

    _append(jsonl, ("k2", "v2"))
    _restart(db, jsonl)

    assert "k2" in _keys(db), "the legacy .migrated sentinel still suppresses the import"


def test_nothing_is_read_twice(tmp_path):
    """Cheap to get wrong: an offset that does not advance re-imports every start."""
    db, jsonl = _home(tmp_path)
    _append(jsonl, ("k1", "v1"))
    _restart(db, jsonl)
    first_offset = (jsonl.parent / "facts.jsonl.offset").read_text(encoding="utf-8")

    _restart(db, jsonl)
    _restart(db, jsonl)

    assert (jsonl.parent / "facts.jsonl.offset").read_text(encoding="utf-8") == first_offset
    assert _keys(db) == {"k1": "v1"}


def test_a_torn_last_line_is_picked_up_on_the_next_start(tmp_path):
    """A writer killed mid-append leaves half a line; it is not lost, just late.

    The torn tail must not be imported (it is not valid JSON yet) and must not
    be skipped forever either: the writer finishes the same bytes on its next
    attempt, and that is when the line becomes readable.
    """
    db, jsonl = _home(tmp_path)
    _restart(db, jsonl)  # database exists, no jsonl yet
    _append(jsonl, ("done", "yes"))

    # half a record, exactly as a killed process would leave it
    tail = FACT.format(key="torn", value="later")
    cut = len(tail) // 2
    jsonl.write_text(jsonl.read_text(encoding="utf-8") + tail[:cut], encoding="utf-8")
    _restart(db, jsonl)
    assert "torn" not in _keys(db), "a half-written line was imported as if it were whole"

    # the writer retries and writes the rest of that record plus the newline
    with jsonl.open("a", encoding="utf-8") as handle:
        handle.write(tail[cut:] + "\n")
    _restart(db, jsonl)

    keys = _keys(db)
    assert keys.get("done") == "yes"
    assert keys.get("torn") == "later", "the rest of the torn line was skipped forever"


def test_a_rotated_file_does_not_swallow_facts(tmp_path):
    """Older file is bigger than the new one: the offset must reset, not run past the end."""
    db, jsonl = _home(tmp_path)
    _append(jsonl, *[(f"old{i}", "v") for i in range(50)])
    _restart(db, jsonl)
    assert len(_keys(db)) == 50

    jsonl.write_text(FACT.format(key="fresh", value="v") + "\n", encoding="utf-8")  # rotated
    _restart(db, jsonl)

    assert "fresh" in _keys(db), "after a rotation the importer stayed pinned past the end"


def test_broken_lines_do_not_stop_the_good_ones(tmp_path):
    db, jsonl = _home(tmp_path)
    jsonl.write_text("{not json\n", encoding="utf-8")
    _append(jsonl, ("good", "v"))
    _restart(db, jsonl)
    assert _keys(db).get("good") == "v"


def test_a_missing_jsonl_is_not_an_error(tmp_path):
    db, jsonl = _home(tmp_path)
    _restart(db, jsonl)  # nothing to import, and nothing to complain about
    assert not jsonl.exists()
    assert _keys(db) == {}
