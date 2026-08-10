#!/usr/bin/env python3
"""Fail-closed guard: the requirement sets must not contradict each other.

Why this exists
---------------
check_lock_freshness.py verifies each `.in`/`.lock` pair against *itself*.
Nothing verified the pairs against *each other*, and two ways of
disagreeing were both live in the tree when this guard was written.

1. Two `.in` files declaring the same tool at different versions.

   requirements-ci.in pinned ruff==0.16.1 and requirements-lint.in pinned
   ruff==0.16.2. Both are installed by CI, in different jobs, and both run
   a ruff gate: the "Lint (ruff)" job installs the lint lock, while the
   "Debt totals" job installs the CI lock and then runs
   scripts/lint_ratchet.py, which shells out to whichever ruff is on PATH.
   So the repository had two linters of record. A rule added, removed or
   changed between those two releases produces a verdict that depends on
   which job you read, and the ratchet baseline can only be correct for
   one of them. Every pin was hash-locked and every check was green; the
   pins simply disagreed, and nothing was looking.

2. Two locks installed into the *same* environment disagreeing on a
   shared package.

   Three jobs install two locks back to back into one interpreter
   (packaging-e2e, e2e-installed, mutation sweep). pip resolves that by
   letting the second install win, silently replacing a version the first
   lock hash-verified. The `--require-hashes` armour is intact and
   meaningless: the environment that runs the tests is a version nobody
   pinned. That combination happens to be conflict-free today, which is
   exactly when to nail it down.

What is checked
---------------
  1. DIRECT declarations (the `.in` files) must agree on a version
     wherever the same distribution is declared more than once.
  2. Locks that are installed into the same job environment must agree on
     every package they share, transitive ones included.

What is deliberately NOT checked: agreement between locks that never meet.
requirements-security.lock resolves rich/packaging/cffi differently from
requirements-ci.lock because its own dependency graph demands it, and no
job installs both. Forcing unrelated resolutions to match would produce
failures with nothing behind them, and a gate that cries wolf gets
disabled — the co-installation map is read out of the workflows so the
check only fires where a conflict can actually reach an interpreter.

Usage:  python3 scripts/lock_conflict_ratchet.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WORKFLOWS = ROOT / ".github" / "workflows"

IN_REQ = re.compile(
    r"^(?P<name>[A-Za-z0-9][A-Za-z0-9._-]*)"
    r"(?P<extras>\[[^\]]+\])?"
    r"==(?P<version>[^\s;#]+)"
)
LOCK_PIN = re.compile(
    r"^(?P<name>[A-Za-z0-9][A-Za-z0-9._-]*)==(?P<version>[^\s;\\]+)"
)
# `pip install --require-hashes -r requirements-<x>.lock`, however the
# surrounding command is spelled (python -m pip, a venv's pip, quoted path).
LOCK_INSTALL = re.compile(r"-r\s+(requirements-[A-Za-z0-9_.-]+\.lock)")


def canonical(name: str) -> str:
    """PEP 503 normalisation: import-linter == import_linter == Import.Linter."""
    return re.sub(r"[-_.]+", "-", name).lower()


def parse_in(path: Path) -> dict[str, str]:
    reqs: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        m = IN_REQ.match(line)
        if m:
            reqs[canonical(m.group("name"))] = m.group("version")
    return reqs


def parse_lock(path: Path) -> dict[str, str]:
    pins: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        m = LOCK_PIN.match(line)
        if m:
            pins[canonical(m.group("name"))] = m.group("version")
    return pins


def check_direct_declarations() -> list[str]:
    """Rule 1: the same distribution pinned twice must be pinned identically."""
    declared: dict[str, dict[str, str]] = {}
    for in_path in sorted(ROOT.glob("requirements-*.in")):
        for name, version in parse_in(in_path).items():
            declared.setdefault(name, {})[in_path.name] = version

    problems: list[str] = []
    for name, by_file in sorted(declared.items()):
        versions = set(by_file.values())
        if len(versions) > 1:
            where = ", ".join(f"{f} wants {v}" for f, v in sorted(by_file.items()))
            problems.append(
                f"'{name}' is declared at conflicting versions: {where}. "
                f"Two pins for one tool means two verdicts of record; pick "
                f"one version, put it in every .in that needs it, and "
                f"regenerate the affected locks."
            )
    return problems


def co_installed_lock_groups() -> dict[str, set[str]]:
    """Map 'workflow::job' -> set of lock files that job installs.

    Read from the workflow text rather than a hand-maintained list: a new
    job that combines two locks must not be able to appear without this
    guard noticing it.
    """
    groups: dict[str, set[str]] = {}
    if not WORKFLOWS.is_dir():
        return groups

    job_header = re.compile(r"^  (?P<job>[A-Za-z0-9_-]+):\s*$")
    for wf in sorted(WORKFLOWS.glob("*.yml")):
        job: str | None = None
        for raw in wf.read_text(encoding="utf-8").splitlines():
            m = job_header.match(raw)
            if m:
                job = m.group("job")
            for lock in LOCK_INSTALL.findall(raw):
                if job is not None:
                    groups.setdefault(f"{wf.name}::{job}", set()).add(lock)
    return {k: v for k, v in groups.items() if len(v) > 1}


def check_co_installed_locks() -> list[str]:
    """Rule 2: locks sharing an interpreter must agree on shared packages."""
    problems: list[str] = []
    for job, locks in sorted(co_installed_lock_groups().items()):
        resolved: dict[str, dict[str, str]] = {}
        for lock in sorted(locks):
            path = ROOT / lock
            if not path.exists():
                problems.append(
                    f"{job} installs {lock}, which does not exist in the "
                    f"repository — the job cannot be doing what it says."
                )
                continue
            for name, version in parse_lock(path).items():
                resolved.setdefault(name, {})[lock] = version

        for name, by_lock in sorted(resolved.items()):
            if len(set(by_lock.values())) > 1:
                where = ", ".join(f"{f} pins {v}" for f, v in sorted(by_lock.items()))
                problems.append(
                    f"{job} installs both locks into one environment and they "
                    f"disagree on '{name}': {where}. The second install "
                    f"silently overwrites the first, so the tested version is "
                    f"whichever pip touched last."
                )
    return problems


def main() -> int:
    in_files = sorted(ROOT.glob("requirements-*.in"))
    if not in_files:
        print(
            "no requirements-*.in files found — this guard is looking in the "
            "wrong place, fix it before trusting its OK",
            file=sys.stderr,
        )
        return 2

    problems = check_direct_declarations() + check_co_installed_locks()
    if problems:
        print("REQUIREMENT CONFLICTS:", file=sys.stderr)
        for p in problems:
            print(f"  - {p}", file=sys.stderr)
        return 1

    groups = co_installed_lock_groups()
    print(
        f"OK: {len(in_files)} .in file(s) agree on every shared direct pin; "
        f"{len(groups)} job(s) installing multiple locks have no shared-package "
        f"conflict."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
