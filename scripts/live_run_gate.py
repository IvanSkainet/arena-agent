#!/usr/bin/env python3
"""Decide whether a local pytest run may be compared against a baseline.

Written after a run that was silently thrown away looked like a clean
one (#331). The pre-merge check on the Windows host compares failure ids
against a baseline captured on master; the arithmetic is sound and the
conclusion was still wrong, because the run had died a tenth of the way
through:

    gate: 0  baseline: 30
    === new ===
    (empty)

Zero failures against thirty reads as an improvement. Nothing in the
comparison could notice: an interrupted run does not report the failures
it never reached, and "no new failures" was, narrowly, true. What was
missing is the question asked here first -- did this run actually finish?

The three signals are deliberately redundant, because each one alone has
been observed to lie:

* `RUN_FINISHED`, appended by the .bat wrapper, only proves the wrapper
  resumed. `pytest` dying by `os._exit` still lets the next line run.
* The progress marker `[100%]` is printed by the terminal reporter, so
  it is absent on a killed run -- but also absent under `-p no:terminal`
  and on some `-q` paths, so its absence alone is not proof of death.
* The summary line (`N passed`, `M failed`) is the only one that comes
  from pytest having reached the end of the session, which is why a run
  missing it is rejected even when the other two are present.

Usage:

    python scripts/live_run_gate.py run.txt --baseline-count 30

Exit status is 0 only when the run is complete and comparable.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

# The closing line, with or without the `=====` rule around it: pytest
# prints `===== 1 failed, 215 passed in 210.11s =====` by default and a
# bare `220 passed in 180.00s` under `-q`. The `in <seconds>s` tail is
# the part that only appears once the session has ended, so that is what
# is matched rather than the decorations around it.
_SUMMARY = re.compile(
    r"^[=\s]*(?:\x1b\[[0-9;]*m)?\d+\s+"
    r"(?:passed|failed|error|errors|skipped|xfailed|xpassed)\b"
    r".*\bin\s+[\d.]+s",
    re.MULTILINE,
)
_PROGRESS_COMPLETE = re.compile(r"\[\s*100%\]")
_COUNTER = re.compile(r"(\d+)\s+(passed|failed|errors?|skipped|xfailed|xpassed)")
_COLLECTED = re.compile(r"^collected\s+(\d+)\s+items?", re.MULTILINE)
# pytest's banner. A capture holding more than one run must be judged on
# its last one: the markers of an earlier, completed run would otherwise
# vouch for a later one that died (coderabbit).
_SESSION_START = re.compile(
    r"^(?:\x1b\[[0-9;]*m)*=+\s*test session starts\s*=+", re.MULTILINE)

# A run that finished but executed far fewer tests than the baseline did
# is not comparable either -- a collection error in one file removes its
# tests without failing anything. 5% is loose on purpose: the suite grows
# between runs, and a gate that cries wolf gets bypassed.
_SHRINK_TOLERANCE = 0.05


class Incomplete(Exception):
    """The run cannot be compared, with the reason a human needs."""


def _counters(text: str) -> dict[str, int]:
    """Outcome counts, taken from the summary line itself.

    Read from the matched summary rather than from a fixed-size tail of
    the log. The tail was `text[-4000:]`, chosen when the only sample
    was a short run; anything printed after the summary -- a coverage
    table, teardown warnings -- pushes the counts out of that window and
    the gate then reports a finished run as having executed nothing
    (corgea, cubic, aikido, separately).
    """
    # The first summary at or after the last `[100%]`, not the last one
    # in the file. `matches[-1]` let any later line of the same shape --
    # a captured log, a tool's own output -- override the real counts,
    # which would make a truncated run look big enough to pass the
    # shrink check (cubic). Verified: a bare `9999 passed in 900.00s`
    # after a real `2 failed, 8 passed` was taken as the result.
    progress = list(_PROGRESS_COMPLETE.finditer(text))
    start = progress[-1].end() if progress else 0
    matches = [m for m in _SUMMARY.finditer(text) if m.start() >= start]
    if not matches:
        return {}
    line = text[matches[0].start():matches[0].end()]
    return {kind.rstrip("s"): int(n) for n, kind in _COUNTER.findall(line)}


def _executed(text: str) -> int:
    counts = _counters(text)
    return sum(v for k, v in counts.items() if k != "collected")


def _reject_unfinished_session(text: str) -> None:
    """The two signals that say the session never reached its end.

    Both are required, and neither survives `os._exit` -- that is the
    point. The summary is printed only when pytest reaches the end of
    its session normally, so its absence is what exposes a run killed
    mid-suite; `[100%]` catches the other shape, a run that reached the
    reporter and summarised an interruption (cubic). The `-qq` trap that hides the summary is
    a wrapper bug, reported as such rather than tolerated here (cubic,
    aikido).
    """
    if not _SUMMARY.search(text):
        raise Incomplete(
            "no pytest summary line, so nothing proves the session reached "
            "its end. pytest prints it only on normal completion; on "
            "Windows pytest-timeout has no SIGALRM and ends a stuck test by "
            "calling os._exit(1), which kills the run mid-suite before the "
            "line is written, and the failure list is then a prefix, not a "
            "result (#331).\n"
            "If the run did finish: pyproject.toml already puts -q in "
            "addopts, so passing -q again makes -qq and pytest stops "
            "printing the summary. Drop the extra -q from the wrapper -- do "
            "not weaken this check, it is the only signal that survives "
            "os._exit."
        )
    if not _PROGRESS_COMPLETE.search(text):
        raise Incomplete(
            "the progress counter never reached [100%], so tests were still "
            "outstanding when the log ended."
        )


def _shrink_reason(text: str, executed: int, baseline_count: int | None) -> str:
    """Why this finished run is too small to compare, or "" if it is not.

    Kept as one question with three sources, rather than three guard
    clauses: they all answer "did enough of the suite actually run", and
    a caller only ever needs the first true answer.
    """
    if executed == 0:
        return "the summary reports no tests at all."

    collected = _COLLECTED.search(text)
    if collected and executed < int(collected.group(1)) * (1 - _SHRINK_TOLERANCE):
        return (f"collected {collected.group(1)} tests but only {executed} "
                "ran; the session ended early.")

    if baseline_count is not None and baseline_count <= 0:
        # Zero disables the size check exactly as thoroughly as a
        # negative does -- `executed < 0` is never true -- and a real
        # baseline is always a large positive count, so either is the
        # command-line typo this guard exists to catch (cubic).
        return f"baseline count {baseline_count} is not positive."

    if baseline_count is not None and executed < baseline_count * (1 - _SHRINK_TOLERANCE):
        return (f"{executed} tests ran against a baseline of "
                f"{baseline_count}. A run this much smaller reports fewer "
                "failures than the baseline for the wrong reason -- it "
                "looks like an improvement.")

    return ""


def _last_session(text: str) -> str:
    """The final pytest run in the capture, ignoring any before it.

    A log holding two runs -- an append instead of a truncate, or a
    retry pasted after the first attempt -- otherwise lets the earlier
    run's summary and `[100%]` vouch for a later one that never
    finished (coderabbit). The wrapper truncates today, so this is
    insurance rather than an observed failure.
    """
    starts = list(_SESSION_START.finditer(text))
    return text[starts[-1].start():] if starts else text


def check(text: str, *, baseline_count: int | None = None) -> dict[str, object]:
    """Raise `Incomplete` unless this run reached the end of the session."""
    text = _last_session(text)
    _reject_unfinished_session(text)
    executed = _executed(text)
    if reason := _shrink_reason(text, executed, baseline_count):
        raise Incomplete(reason)
    return {"executed": executed, **_counters(text)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("log", type=Path, help="captured pytest output")
    parser.add_argument(
        "--baseline-count", type=int, default=None,
        help="how many tests the baseline run executed",
    )
    args = parser.parse_args(argv)

    try:
        text = args.log.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        print(f"cannot read the run log: {exc}", file=sys.stderr)
        return 2

    try:
        result = check(text, baseline_count=args.baseline_count)
    except Incomplete as exc:
        print(f"run is NOT comparable: {exc}", file=sys.stderr)
        return 1

    print(f"run is complete: {result['executed']} tests executed "
          f"({result.get('failed', 0)} failed)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
