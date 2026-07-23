"""Diagnose a stuck arena-agent auto-update from the mover's own log.

`arena/admin/auto_update_windows.py:_write_windows_installer` writes
``<install_root>/.arena-update-apply.log`` next to the mover script it
drops on disk. The log is a sequence of ``[DATE TIME] marker`` lines,
one per phase, so an operator can tell at a glance whether the mover
got past the bridge-exit wait, the file copy, and the relaunch.

This script is read-only: it never touches the mover or the running
bridge. It scans the install root, picks the most recent log (or
every log if ``--all``), parses the markers, and prints a short
human-readable summary.

Usage (from the bridge's repo root):

    python scripts/inspect_update_log.py
    python scripts/inspect_update_log.py --all
    python scripts/inspect_update_log.py --root C:/Users/Ivan/Downloads/arena-agent-v4.60.20/arena-bridge

The script has no third-party dependencies and works on any platform
(it's the operator who runs it, not the bridge).
"""
from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Iterable


# Lines emitted by arena/admin/auto_update_windows.py:_write_windows_installer.
# The phase ordering is part of the protocol -- if a phase is missing the
# mover either died or got edited. We surface that explicitly in the report.
PHASE_ORDER: tuple[str, ...] = (
    "mover-start",
    "wait-loop-entry",
    "bridge exited",
    "copy done",
    "relaunched",
    "mover-done",
)

# Optional phases whose absence is *not* a failure but is worth showing.
OPTIONAL_PHASES: dict[str, str] = {
    "relaunched via schtasks": "Scheduled Task path was used",
    "relaunched via start_hidden.vbs": "start_hidden.vbs path was used",
    "relaunched via start_bridge.bat": "start_bridge.bat path was used",
    "WARN no relaunch mechanism found": "No relaunch mechanism matched -- bridge will stay down",
}

# Lines we don't recognise but still print, so an operator can spot a new
# marker we haven't catalogued yet.
_LINE_RE = re.compile(
    r"^\[(?P<date>\d{4}-\d{2}-\d{2})\s+(?P<time>\d{2}:\d{2}:\d{2}\.\d+)\]\s+(?P<rest>.*)$"
)


@dataclass(frozen=True)
class LogEntry:
    when: datetime
    marker: str
    detail: str = ""

    def short(self) -> str:
        return f"[{self.when:%Y-%m-%d %H:%M:%S}] {self.marker}{(' ' + self.detail) if self.detail else ''}"


@dataclass
class LogReport:
    path: Path
    entries: list[LogEntry] = field(default_factory=list)
    parse_errors: list[str] = field(default_factory=list)

    @property
    def phases_seen(self) -> list[str]:
        out: list[str] = []
        for e in self.entries:
            # The marker is whatever the mover wrote before its first
            # space. Some markers are full phrases (e.g. ``bridge
            # exited, starting copy``) that the parser splits into
            # ``marker="bridge"`` + ``detail="exited, starting copy"``,
            # so we search the joined text. ``mover-done`` is a
            # single-token marker, so prefix-match is enough there.
            haystack = (e.marker + " " + e.detail).strip()
            for phase in PHASE_ORDER:
                if haystack.startswith(phase) and phase not in out:
                    out.append(phase)
        return out

    @property
    def missing_phases(self) -> list[str]:
        seen = set(self.phases_seen)
        return [p for p in PHASE_ORDER if p not in seen]

    @property
    def final_phase(self) -> str:
        if not self.entries:
            return "<no entries>"
        last = self.entries[-1]
        haystack = (last.marker + " " + last.detail).strip()
        best = "<unknown>"
        for phase in PHASE_ORDER:
            if haystack.startswith(phase) and len(phase) > len(best):
                best = phase
        return best

    @property
    def finished_cleanly(self) -> bool:
        return any(e.marker.startswith("mover-done") for e in self.entries)

    @property
    def relaunched_via(self) -> str | None:
        for e in self.entries:
            haystack = (e.marker + " " + e.detail).strip()
            for tag, label in OPTIONAL_PHASES.items():
                if tag in haystack and "relaunched" in tag:
                    return label
        return None


def _parse_log(path: Path) -> LogReport:
    rep = LogReport(path=path)
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except Exception as e:
        rep.parse_errors.append(f"read failed: {e!r}")
        return rep
    for n, line in enumerate(text.splitlines(), 1):
        line = line.rstrip("\r")
        m = _LINE_RE.match(line)
        if not m:
            if line.strip():
                rep.parse_errors.append(f"L{n}: unrecognised line: {line!r}")
            continue
        try:
            when = datetime.strptime(
                f"{m.group('date')} {m.group('time')}", "%Y-%m-%d %H:%M:%S.%f"
            )
        except ValueError as e:
            rep.parse_errors.append(f"L{n}: bad timestamp: {e}")
            continue
        rest = m.group("rest").strip()
        # The marker is everything up to the first whitespace;
        # any extra text is a "detail" (e.g. pid_target=1234).
        marker, _, detail = rest.partition(" ")
        rep.entries.append(LogEntry(when=when, marker=marker, detail=detail))
    return rep


def _resolve_log_paths(root: Path, all_logs: bool) -> list[Path]:
    if not root.exists():
        return []
    if all_logs:
        return sorted(
            p for p in root.glob(".arena-update-apply*.log")
            if p.is_file()
        )
    # Newest first.
    candidates = sorted(
        (p for p in root.glob(".arena-update-apply*.log") if p.is_file()),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    return candidates[:1]


def _print_report(rep: LogReport, *, verbose: bool = False) -> None:
    if rep.parse_errors:
        for err in rep.parse_errors:
            print(f"  WARN: {err}", file=sys.stderr)
    if not rep.entries:
        print(f"  (no parseable entries)")
        return
    if verbose:
        for e in rep.entries:
            print(f"  {e.short()}")
    else:
        # First + last, plus any WARN line.
        first = rep.entries[0]
        print(f"  start: {first.short()}")
        if len(rep.entries) > 2:
            print(f"  ... {len(rep.entries) - 2} more entries (use --verbose to see all)")
        last = rep.entries[-1]
        if last is not first:
            print(f"  last:  {last.short()}")
    seen = rep.phases_seen
    missing = rep.missing_phases
    print(f"  phases seen:    {', '.join(seen) or '<none>'}")
    if missing:
        print(f"  phases missing: {', '.join(missing)}")
    via = rep.relaunched_via
    if via:
        print(f"  relaunch:       {via}")
    if rep.finished_cleanly:
        print(f"  status:         OK (mover-done present)")
    else:
        print(
            f"  status:         INCOMPLETE -- last phase was "
            f"{rep.final_phase!r}; bridge may still be down",
            file=sys.stderr,
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Inspect arena-agent's auto-update mover log."
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=None,
        help="Install root to scan (default: <repo>/arena-bridge or this script's parent).",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Print a report for every .arena-update-apply*.log under the root.",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Print every parsed log entry, not just first/last.",
    )
    args = parser.parse_args(argv)

    if args.root is not None:
        root = args.root.resolve()
    else:
        # Default: the install root is one level up from this script's
        # parent (which is the repo root in dev checkouts, and the
        # arena-bridge dir in installed copies).
        here = Path(__file__).resolve().parent
        root = here.parent

    paths = _resolve_log_paths(root, all_logs=args.all)
    if not paths:
        print(f"No .arena-update-apply*.log found under {root}")
        print("(either no auto-update was ever run here, or the log was already pruned)")
        return 1

    rc = 0
    for p in paths:
        print(f"=== {p}")
        rep = _parse_log(p)
        _print_report(rep, verbose=args.verbose)
        print()
        if not rep.finished_cleanly:
            rc = 2
    return rc


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
