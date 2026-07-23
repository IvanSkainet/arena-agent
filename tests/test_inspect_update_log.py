"""Tests for scripts/inspect_update_log.py.

The mover log is the only post-mortem artifact for a stuck
auto-update, so its parser must be robust to the exact line shape
emitted by arena/admin/auto_update_windows.py plus the realistic
garbage an operator might leave behind.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

# scripts/ is not on sys.path by default in this repo (the install
# flow puts it there, but pytest collects from tests/ directly).
_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO / "scripts"))

from inspect_update_log import (  # noqa: E402  -- import after sys.path tweak
    LogEntry,
    LogReport,
    PHASE_ORDER,
    _LINE_RE,
    _parse_log,
    _resolve_log_paths,
    main,
)


# A canonical, complete log: bridge exited, files copied, bridge relaunched.
GOOD_LOG = (
    "[2026-07-23 10:00:00.000] mover-start pid_target=1234\n"
    "[2026-07-23 10:00:00.500] wait-loop-entry\n"
    "[2026-07-23 10:00:05.123] bridge exited, starting copy\n"
    "[2026-07-23 10:00:07.456] copy done, launching relaunch\n"
    "[2026-07-23 10:00:07.500] relaunched via schtasks\n"
    "[2026-07-23 10:00:07.600] mover-done\n"
)


def test_line_regex_accepts_canonical_shape():
    m = _LINE_RE.match("[2026-07-23 10:00:00.000] mover-start pid_target=1234")
    assert m is not None
    assert m.group("date") == "2026-07-23"
    assert m.group("time") == "10:00:00.000"
    assert m.group("rest") == "mover-start pid_target=1234"


def test_line_regex_accepts_marker_with_no_detail():
    m = _LINE_RE.match("[2026-07-23 10:00:00.000] wait-loop-entry")
    assert m is not None
    assert m.group("rest") == "wait-loop-entry"


def test_parse_good_log_records_all_entries(tmp_path):
    log = tmp_path / ".arena-update-apply.log"
    log.write_text(GOOD_LOG, encoding="utf-8")
    rep = _parse_log(log)
    assert len(rep.parse_errors) == 0
    assert len(rep.entries) == 6
    assert [e.marker for e in rep.entries] == [
        "mover-start", "wait-loop-entry", "bridge",
        "copy", "relaunched", "mover-done",
    ]
    # First entry keeps the pid_target detail.
    assert rep.entries[0].detail == "pid_target=1234"


def test_parse_records_final_phase_as_in_clean_log(tmp_path):
    log = tmp_path / ".arena-update-apply.log"
    log.write_text(GOOD_LOG, encoding="utf-8")
    rep = _parse_log(log)
    assert rep.finished_cleanly is True
    assert rep.final_phase == "mover-done"
    assert rep.missing_phases == []
    # The "bridge" / "copy" markers are prefix-matched against PHASE_ORDER,
    # so they should count as having seen the "bridge exited" / "copy done"
    # phases.
    assert "bridge exited" in rep.phases_seen
    assert "copy done" in rep.phases_seen
    assert rep.relaunched_via == "Scheduled Task path was used"


def test_parse_incomplete_log_reports_missing_phases(tmp_path):
    """If the mover dies after 'mover-start' but before 'bridge exited',
    the operator should see exactly which phase the script stalled at."""
    log = tmp_path / ".arena-update-apply.log"
    log.write_text(
        "[2026-07-23 10:00:00.000] mover-start pid_target=1234\n"
        "[2026-07-23 10:00:00.500] wait-loop-entry\n",
        encoding="utf-8",
    )
    rep = _parse_log(log)
    assert rep.finished_cleanly is False
    assert rep.missing_phases == ["bridge exited", "copy done", "relaunched", "mover-done"]
    assert rep.final_phase == "wait-loop-entry"


def test_parse_warn_no_relaunch(tmp_path):
    log = tmp_path / ".arena-update-apply.log"
    log.write_text(
        "[2026-07-23 10:00:00.000] mover-start pid_target=1234\n"
        "[2026-07-23 10:00:00.500] wait-loop-entry\n"
        "[2026-07-23 10:00:05.123] bridge exited, starting copy\n"
        "[2026-07-23 10:00:07.456] copy done, launching relaunch\n"
        "[2026-07-23 10:00:08.000] WARN no relaunch mechanism found\n"
        "[2026-07-23 10:00:08.001] mover-done\n",
        encoding="utf-8",
    )
    rep = _parse_log(log)
    assert rep.finished_cleanly is True
    # The "WARN" line is its own marker, not "relaunched", so relaunch_via
    # returns None -- the operator should see the WARN line as the last
    # actionable hint, which the printer surfaces.
    assert rep.relaunched_via is None


def test_parse_ignores_blank_lines_and_unrecognised_lines(tmp_path):
    log = tmp_path / ".arena-update-apply.log"
    log.write_text(
        "\n"
        "[2026-07-23 10:00:00.000] mover-start pid_target=1234\n"
        "\n"
        "this is garbage from a copy-paste mistake\n"
        "[2026-07-23 10:00:00.500] wait-loop-entry\n",
        encoding="utf-8",
    )
    rep = _parse_log(log)
    # One real entry lost to garbage; the other two parse fine.
    assert len(rep.entries) == 2
    assert len(rep.parse_errors) == 1
    assert "unrecognised line" in rep.parse_errors[0]


def test_parse_read_failure_does_not_raise(tmp_path):
    """Reading a directory as a log must surface a parse error, not
    crash the whole tool."""
    log = tmp_path / "not-a-file.log"
    log.mkdir()
    rep = _parse_log(log)
    assert rep.parse_errors and "read failed" in rep.parse_errors[0]
    assert rep.entries == []


def test_resolve_log_paths_picks_newest_when_not_all(tmp_path):
    (tmp_path / ".arena-update-apply_111.log").write_text("old")
    new = tmp_path / ".arena-update-apply_999.log"
    new.write_text("new")
    # Force mtime ordering so the test is stable across filesystems.
    import os
    os.utime(tmp_path / ".arena-update-apply_111.log", (1_000_000, 1_000_000))
    os.utime(new, (2_000_000, 2_000_000))

    picked = _resolve_log_paths(tmp_path, all_logs=False)
    assert picked == [new]


def test_resolve_log_paths_returns_all_when_all(tmp_path):
    for name in (".arena-update-apply_111.log", ".arena-update-apply_222.log"):
        (tmp_path / name).write_text("x")
    # Add an unrelated file that must be ignored.
    (tmp_path / "update.log").write_text("x")
    picked = _resolve_log_paths(tmp_path, all_logs=True)
    names = {p.name for p in picked}
    assert names == {
        ".arena-update-apply_111.log",
        ".arena-update-apply_222.log",
    }


def test_resolve_log_paths_empty_when_no_logs(tmp_path):
    (tmp_path / "unrelated.txt").write_text("x")
    assert _resolve_log_paths(tmp_path, all_logs=True) == []
    assert _resolve_log_paths(tmp_path, all_logs=False) == []


def test_resolve_log_paths_missing_root(tmp_path):
    missing = tmp_path / "does-not-exist"
    assert _resolve_log_paths(missing, all_logs=True) == []
    assert _resolve_log_paths(missing, all_logs=False) == []


def test_main_returns_zero_on_clean_log(tmp_path, capsys):
    log = tmp_path / ".arena-update-apply.log"
    log.write_text(GOOD_LOG, encoding="utf-8")
    rc = main(["--root", str(tmp_path)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "phases seen:" in out
    assert "mover-done" in out
    assert "OK" in out


def test_main_returns_nonzero_on_stalled_log(tmp_path, capsys):
    log = tmp_path / ".arena-update-apply.log"
    log.write_text(
        "[2026-07-23 10:00:00.000] mover-start pid_target=1234\n",
        encoding="utf-8",
    )
    rc = main(["--root", str(tmp_path)])
    assert rc == 2
    err = capsys.readouterr().err
    assert "INCOMPLETE" in err
    assert "mover-start" in err


def test_main_returns_one_when_no_logs(tmp_path, capsys):
    rc = main(["--root", str(tmp_path)])
    assert rc == 1
    out = capsys.readouterr().out
    assert "No .arena-update-apply*.log" in out


def test_main_verbose_prints_every_entry(tmp_path, capsys):
    log = tmp_path / ".arena-update-apply.log"
    log.write_text(GOOD_LOG, encoding="utf-8")
    main(["--root", str(tmp_path), "--verbose"])
    out = capsys.readouterr().out
    # All six entries must appear in verbose mode.
    for marker in (
        "mover-start", "wait-loop-entry", "bridge exited",
        "copy done", "relaunched", "mover-done",
    ):
        assert marker in out, f"verbose output missing {marker!r}"


def test_phase_order_is_total_order():
    """The phase list is part of the protocol; tests reference it by index
    in places, so it must stay a tuple."""
    assert isinstance(PHASE_ORDER, tuple)
    assert len(PHASE_ORDER) == len(set(PHASE_ORDER)), "duplicate phase in PHASE_ORDER"
