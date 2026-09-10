"""The completeness check, checked against the log that fooled me.

`scripts/live_run_gate.py` exists because comparing failure ids to a
baseline cannot tell a clean run from a truncated one: the run that died
after 10% of the suite reported *fewer* failures than the baseline, and
an empty "new failures" list is exactly what a good run produces (#331).

The cases below are the real shapes, not invented ones -- a run killed
by `os._exit` mid-suite, a run whose collection quietly shrank, and an
ordinary complete run that must keep passing.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_GATE = Path(__file__).resolve().parents[1] / "scripts" / "live_run_gate.py"
_spec = importlib.util.spec_from_file_location("_live_run_gate", _GATE)
assert _spec and _spec.loader
live_run_gate = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(live_run_gate)


_COMPLETE = """\
........................................................................ [ 33%]
........................................................................ [ 66%]
....................................F................................... [100%]
=========================== short test summary info ===========================
FAILED tests/test_thing.py::test_one
1 failed, 215 passed, 4 skipped in 210.11s
"""

# What the killed run actually looked like: output stops mid-progress,
# no summary, and the wrapper still appends its own marker afterwards.
_TRUNCATED = """\
........................................................................ [  6%]
....................F................................................... [  8%]
+++++++++++++++++++++++++++++++++++ Timeout +++++++++++++++++++++++++++++++++++
File "C:\\Users\\Ivan\\lv260br\\arena\\mcp\\tool_asr.py", line 380, in _download_atomic
    chunk = r.read(1024 * 1024)
RUN_FINISHED
"""


def test_a_complete_run_is_accepted():
    result = live_run_gate.check(_COMPLETE)
    assert result["failed"] == 1
    assert result["executed"] == 220


def test_the_truncated_run_is_rejected():
    """The case that started this: it reported zero failures and looked good."""
    with pytest.raises(live_run_gate.Incomplete) as caught:
        live_run_gate.check(_TRUNCATED)
    assert "#331" in str(caught.value)


def test_run_finished_alone_does_not_make_a_run_complete():
    """The wrapper's marker only proves the wrapper resumed.

    `os._exit(1)` inside pytest still returns control to the .bat file,
    which appends `RUN_FINISHED` to a log of a run that died. Trusting
    that marker is what let the empty comparison look trustworthy.
    """
    assert "RUN_FINISHED" in _TRUNCATED
    with pytest.raises(live_run_gate.Incomplete):
        live_run_gate.check(_TRUNCATED)


def test_a_run_with_neither_end_of_session_signal_is_rejected():
    """Neither a summary nor `[100%]`: nothing says the session ended.

    Named for what it actually asserts. It strips the summary as well as
    the marker, so the rejection comes from the summary check; the
    99%-with-a-summary case belongs to
    `test_a_summary_without_a_finished_progress_bar_is_rejected`, which
    is the test that exercises the `[100%]` check on its own (cubic).
    """
    almost = _COMPLETE.replace("[100%]", "[ 99%]").replace(
        "1 failed, 215 passed, 4 skipped in 210.11s", "")
    with pytest.raises(live_run_gate.Incomplete):
        live_run_gate.check(almost)


def test_a_summary_without_a_finished_progress_bar_is_rejected():
    """Both signals are load-bearing; neither implies the other.

    A run can print a summary line after being interrupted -- pytest
    summarises what it managed -- so the progress counter is checked
    separately. Mutation found this: deleting the `[100%]` check left
    every other test green.
    """
    interrupted = """\
........................................................................ [ 41%]
!!!!!!!!!!!!!!!!!!!!!!!!!! KeyboardInterrupt !!!!!!!!!!!!!!!!!!!!!!!!!!
90 passed, 2 failed in 45.00s
"""
    with pytest.raises(live_run_gate.Incomplete) as caught:
        live_run_gate.check(interrupted)
    assert "100%" in str(caught.value)


def test_a_run_reporting_no_tests_at_all_is_rejected():
    """`0 passed` with a tidy summary is not a passing run.

    A collection failure in a shared conftest empties the session while
    leaving the output looking orderly. Also found by mutation.
    """
    empty = """\
                                                                         [100%]
0 passed in 0.02s
"""
    with pytest.raises(live_run_gate.Incomplete) as caught:
        live_run_gate.check(empty)
    assert "no tests" in str(caught.value)


def test_a_shrunken_collection_is_rejected():
    """A collection error removes tests without failing anything.

    The suite still finishes and still reports no new failures -- while
    silently no longer running the file that broke.
    """
    shrunk = "collected 900 items\n" + _COMPLETE
    with pytest.raises(live_run_gate.Incomplete) as caught:
        live_run_gate.check(shrunk)
    assert "ended early" in str(caught.value)


def test_a_run_far_smaller_than_the_baseline_is_rejected():
    with pytest.raises(live_run_gate.Incomplete) as caught:
        live_run_gate.check(_COMPLETE, baseline_count=2000)
    assert "improvement" in str(caught.value)


def test_a_slightly_smaller_run_is_still_accepted():
    """The suite changes between runs; a gate that cries wolf gets bypassed."""
    assert live_run_gate.check(_COMPLETE, baseline_count=225)


def test_an_all_passing_run_is_accepted():
    """Nothing failed and nothing is wrong -- the gate is about completeness."""
    clean = """\
........................................................................ [100%]
220 passed in 180.00s
"""
    assert live_run_gate.check(clean)["executed"] == 220


def test_the_exit_status_is_what_a_shell_can_branch_on(tmp_path):
    """The .bat wrapper reads the status, not the wording."""
    log = tmp_path / "run.txt"
    log.write_text(_TRUNCATED, encoding="utf-8")
    assert live_run_gate.main([str(log)]) == 1

    log.write_text(_COMPLETE, encoding="utf-8")
    assert live_run_gate.main([str(log)]) == 0


def test_a_qq_log_without_a_summary_names_the_duplicate_flag():
    """`-qq` hides the summary, and the gate must say why.

    `addopts` in pyproject.toml already contains `-q`, so a wrapper
    passing `-q` produces `-qq` and pytest prints no summary line. That
    is a wrapper bug: weakening the check would give up the one signal
    that survives `os._exit` on Windows. The message has to point at the
    duplicate flag, or the next person reads this as the gate being
    broken (cubic, aikido).
    """
    qq = ("........................................................ [100%]\n"
          "=========================== short test summary info ===========\n"
          "FAILED tests/test_one.py::test_a - assert False\n")
    with pytest.raises(live_run_gate.Incomplete) as caught:
        live_run_gate.check(qq)
    assert "-qq" in str(caught.value)


def test_counters_survive_output_printed_after_the_summary():
    """A coverage table after the summary must not hide the counts.

    The counters used to be read from `text[-4000:]`. The repository
    prints `--cov-report=term-missing`, which is far longer than that,
    so a genuinely complete run reported zero executed tests and the
    gate rejected it (corgea, cubic, aikido). Reading the summary line
    itself is what makes the size of the trailing output irrelevant.
    """
    noisy = _COMPLETE + "\n" + "arena/some/module.py   123   45   63%\n" * 400
    assert len(noisy) - noisy.index("215 passed") > 4000
    assert live_run_gate.check(noisy)["passed"] == 215


@pytest.mark.parametrize("baseline", [0, -1])
def test_a_non_positive_baseline_is_refused(baseline):
    """`--baseline-count 0` disables the size check as fully as `-1`.

    `executed < 0 * (1 - tolerance)` is never true, so a truncated run
    would be reported as comparable. A real baseline is always a large
    positive count, so either value is the typo the guard catches
    (cubic).
    """
    with pytest.raises(live_run_gate.Incomplete) as caught:
        live_run_gate.check(_COMPLETE, baseline_count=baseline)
    assert "not positive" in str(caught.value)


def test_a_later_summary_shaped_line_cannot_override_the_real_counts():
    """Only the summary belonging to this run may set the counts.

    Taking the last summary-shaped line in the file let anything printed
    afterwards -- a captured log, another tool's output -- replace the
    real result, which is how a truncated run would pass the shrink
    check (cubic). The counts come from the first summary at or after
    the last `[100%]`.
    """
    forged = ("........ [100%]\n"
              "===== 2 failed, 8 passed in 3.0s =====\n"
              "9999 passed in 900.00s\n")
    with pytest.raises(live_run_gate.Incomplete) as caught:
        live_run_gate.check(forged, baseline_count=1000)
    assert "10 tests ran" in str(caught.value)
