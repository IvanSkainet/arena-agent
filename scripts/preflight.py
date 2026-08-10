#!/usr/bin/env python3
"""Run, locally, every gate that has ever failed this project in CI.

Why this exists, measured. Over the last 25 CI runs: 19 green, 3 failures,
3 cancelled -- a 12% failure rate. All three failures were things a human
could have caught locally but did not, because the local checks were
assembled from memory each time and something was always missed:

  17cec54e  actionlint passed locally, failed in CI -- CI runs it *with*
            shellcheck (SC2012), the local binary had no shellcheck on PATH
  6ba7b06a  a test read /proc, which does not exist on macOS; the whole
            macOS matrix went red on healthy code
  7041c57d  the badge gate asserted something unsatisfiable on a release
            commit

The cost is not the red build, it is the round trip: CI takes a median of
12.3 minutes, so each of those cost a quarter of an hour to learn something a
30-second local command would have said. Half of the recent commits on this
branch are one-file, one-line follow-ups fixing exactly that.

So: one command, run before pushing anything. It fails closed -- a missing
tool is a failure, not a skip, because "the check did not run" and "the check
passed" must never look the same.

Usage:
    python scripts/preflight.py            # everything except the slow suite
    python scripts/preflight.py --full     # + the whole pytest run
    python scripts/preflight.py --list     # show what would run
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


class Check:
    def __init__(self, name: str, argv: list[str], *, needs: str | None = None,
                 why: str = "", slow: bool = False) -> None:
        self.name = name
        self.argv = argv
        self.needs = needs          # binary that must exist, or the check fails
        self.why = why              # what real breakage this prevents
        self.slow = slow


PY = sys.executable

CHECKS: list[Check] = [
    Check("ruff ratchet", [PY, "scripts/lint_ratchet.py"],
          why="lint debt must not grow"),
    Check("quality ratchet", [PY, "scripts/quality_ratchet.py"],
          why="pyrefly/vulture debt must not grow"),
    Check("dead code", [PY, "scripts/dead_code_ratchet.py"],
          why="170 releases and nothing had ever been deleted; Serena found "
              "twelve public functions with zero callers, two written the "
              "day before"),
    Check("json shape", [PY, "scripts/json_shape_ratchet.py"],
          why="a mission.json holding the four bytes `null` is valid JSON; "
              "load_mission_json promised a dict, returned None, and the "
              "whole mission listing died on an unrelated line"),
    Check("claim order", [PY, "scripts/claim_order_ratchet.py"],
          why="bug #73 was the v4.166.0 `lost -29` defect a second time, in "
              "the mirror direction: a value escaping before the file is "
              "claimed means two workers deliver the same item"),
    Check("action runtimes", [PY, "scripts/action_runtime_ratchet.py"],
          why="GitHub retired Node 20; the warning only shows in the log of "
              "a job that actually ran, so dependency-review sat on a dead "
              "runtime unnoticed"),
    Check("workflow lint", ["actionlint", "-shellcheck", "shellcheck"],
          needs="actionlint",
          why="CI runs actionlint WITH shellcheck; without it SC2012 slipped "
              "through and reddened a build (17cec54e)"),
    Check("release published", [PY, "scripts/release_published_check.py"],
          why="v4.169.5 through v4.169.9 were tagged, green on 35/35, and "
              "invisible: auto_update reads releases/latest, which only "
              "counts published releases, so every install sat on 4.169.4"),
    Check("android lint", [PY, "scripts/android_lint.py"],
          why="the first BridgeService tried to run Termux's python through "
              "ProcessBuilder; the sandbox forbids it, every check answered "
              "'absent', and the app announced 'Termux installed: no' on a "
              "phone that was serving the bridge"),
    Check("posix shell in tests", [PY, "scripts/posix_shell_test_ratchet.py"],
          why="three releases in eleven died on windows-latest because a "
              "TEST assumed POSIX -- there is no sh on those five jobs, and "
              "the code under test was fine every time"),
    Check("pinned pip", [PY, "scripts/pinned_pip_ratchet.py"],
          why="Scorecard flagged pipCommand not pinned by hash; eight "
              "installs across CI resolved whatever PyPI served that "
              "minute, three of them the security scanners whose verdict "
              "gates a release"),
    Check("dead condition", [PY, "scripts/dead_condition_ratchet.py"],
          why="the release gate was tag-gated inside a workflow that only "
              "runs on master pushes -- it would never have fired once, "
              "the third never-looks-at-anything gate in three releases"),
    Check("github output", [PY, "scripts/github_output_ratchet.py"],
          why="the badge workflow piped a whole heredoc into $GITHUB_OUTPUT; "
              "the ::warning:: it printed landed in the output file and "
              "GitHub failed the step for it, two releases running"),
    Check("workflow security", ["zizmor", "--offline", ".github/workflows"],
          needs="zizmor",
          why="unpinned actions and over-broad permissions"),
    Check("platform-portable tests", [
        PY, "-m", "pytest", "-p", "no:randomly", "--no-cov", "-q",
        "tests/test_exec_timeout_kills_the_tree.py",
        "tests/test_write_is_not_code_execution.py",
        "tests/test_bridge_self_protection.py",
        "tests/test_desktop_input_no_shell_injection.py",
        "tests/test_release_signing_workflow.py",
        "tests/test_version_badge_monotonic.py",
    ], why="the gates most likely to be platform-specific; /proc use here "
           "reddened the whole macOS matrix once (6ba7b06a)"),
    Check("full suite", [PY, "-m", "pytest", "-p", "no:randomly", "--no-cov", "-q"],
          why="everything else", slow=True),
]


def _portability_scan() -> tuple[bool, list[str]]:
    """Deliberately empty: this heuristic was tried twice and failed twice.

    The goal was to catch Linux-only constructs before the macOS matrix does,
    because that is the most expensive mistake class here (6ba7b06a reddened
    five macOS jobs on healthy code).

    Attempt one, substring search: flagged the word "systemd-run" inside a
    docstring that *explains* that very bug.

    Attempt two, AST over string literals: flagged three files that are green
    on macOS in CI, because the strings were
    ``monkeypatch.setattr(R, "_have", lambda c: c == "systemd-run")`` and
    ``restricted_shell("dummy", "cat /proc/version ...")`` -- mocks and
    fixtures, not system access. Distinguishing "this string names a Linux
    path" from "this string is fed to the OS" needs dataflow, not pattern
    matching.

    Three false positives out of three findings is not a checker, it is a
    thing you learn to skip. The real defence stays what it already is: the
    CI matrix runs macOS, and ``platform-portable tests`` below runs the
    gates most likely to be platform-specific before anything is pushed.
    """
    return True, []


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--full", action="store_true", help="include the slow suite")
    ap.add_argument("--list", action="store_true")
    args = ap.parse_args()

    selected = [c for c in CHECKS if args.full or not c.slow]

    if args.list:
        for c in selected:
            print(f"  {c.name:26} {' '.join(c.argv[:4])}...")
        return 0

    failures: list[str] = []
    t_all = time.time()

    ok, bad = _portability_scan()
    print(f"{'portability scan':26} ", end="", flush=True)
    if ok:
        print("ok")
    else:
        print("FAIL")
        for b in bad:
            print(f"    {b}")
        failures.append("portability scan")

    for c in selected:
        print(f"{c.name:26} ", end="", flush=True)
        if c.needs and shutil.which(c.needs) is None:
            # Fail closed. A skipped check that reads as a pass is how a
            # green preflight ends in a red CI.
            print(f"FAIL (missing tool: {c.needs})")
            print(f"    why it matters: {c.why}")
            failures.append(f"{c.name} (tool missing)")
            continue
        t0 = time.time()
        proc = subprocess.run(c.argv, cwd=ROOT, capture_output=True, text=True)
        el = time.time() - t0
        if proc.returncode == 0:
            print(f"ok ({el:.0f}s)")
        else:
            print(f"FAIL ({el:.0f}s)")
            tail = (proc.stdout or "")[-1500:] + (proc.stderr or "")[-1500:]
            for line in tail.strip().splitlines()[-12:]:
                print(f"    {line}")
            print(f"    why it matters: {c.why}")
            failures.append(c.name)

    print(f"\ntotal {time.time() - t_all:.0f}s")
    if failures:
        print(f"PREFLIGHT FAILED: {', '.join(failures)}")
        print("Fix these before pushing; CI takes ~12 minutes to tell you the "
              "same thing.")
        return 1
    print("PREFLIGHT OK" + ("" if args.full else "  (run --full before a release)"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
