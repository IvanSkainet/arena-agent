#!/usr/bin/env python3
"""Fail-closed guard: pyrefly must keep resolving to the `legacy` preset.

Why this exists
---------------
v4.169.32 removed the mypy package: it was installed by every CI job and
never executed once, because type checking here is pyrefly's job through
`scripts/quality_ratchet.py`.

The obvious follow-up cleanup is the trap. `[tool.mypy]` in
`pyproject.toml` looks like leftover configuration for the tool that was
just deleted. It is not. pyrefly has no config of its own in this
repository and imports its settings from that section, and the mere
PRESENCE of it selects the `legacy` preset:

    No `pyrefly.toml` found -- using settings imported from `[tool.mypy]`
    in your `pyproject.toml` (preset: legacy).

Measured on this tree rather than assumed:

    with    [tool.mypy]:  preset legacy, 0 errors
    without [tool.mypy]:  preset basic,  quality ratchet fails with 11
                          new `missing-import` findings

`basic` reports fewer errors while checking less: it stops verifying
calls and assignments, which is the class of bug this project keeps
finding. A green that means less than the red it replaced.

A `pyrefly.toml` carrying `preset = "legacy"` is NOT an equivalent
replacement -- it produced a different result again (4 errors), so the
import path is load-bearing exactly as it stands.

What is checked
---------------
  1. `[tool.mypy]` is still present in pyproject.toml;
  2. no `pyrefly.toml` has appeared -- its presence silences the import
     entirely and takes over the preset;
  3. pyrefly, when actually run, still announces the `legacy` preset.

Check 3 is the real one: reading the file proves nothing about what the
tool decides. If pyrefly is not installed the guard SKIPS loudly and
still enforces checks 1 and 2 -- it never reports success for a thing it
could not measure.

Check 2 exists because the first draft of this guard did not have it.
Sabotage found the hole: dropping in a `pyrefly.toml` saying
`preset = "basic"` made pyrefly stop printing the preset line at all, so
"could not measure" was reported as a SKIP and the run exited 0 with the
preset silently changed. Absence of evidence was being read as evidence.

Usage:  python3 scripts/pyrefly_preset_ratchet.py
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PYPROJECT = ROOT / "pyproject.toml"
PYREFLY_TOML = ROOT / "pyrefly.toml"
REQUIRED_PRESET = "legacy"
# Whatever pyrefly is pointed at; a small target keeps the guard fast,
# because the preset announcement does not depend on the scope.
PROBE_TARGET = "arena"


def has_mypy_section() -> bool:
    if not PYPROJECT.exists():
        return False
    text = PYPROJECT.read_text(encoding="utf-8")
    # Section header at the start of a line, not a mention inside prose.
    return re.search(r"^\[tool\.mypy\]\s*$", text, re.M) is not None


def observed_preset() -> str | None:
    """Run pyrefly and read the preset it announces. None if unavailable."""
    if shutil.which("pyrefly") is None:
        try:
            import pyrefly  # noqa: F401
        except ImportError:
            return None

    try:
        proc = subprocess.run(
            [sys.executable, "-m", "pyrefly", "check", PROBE_TARGET],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=600,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None

    blob = f"{proc.stdout}\n{proc.stderr}"
    match = re.search(r"preset:\s*([A-Za-z]+)", blob)
    if match:
        return match.group(1).lower()
    # pyrefly prints the import line only when it falls back to a preset;
    # a bare "using preset `basic`" is the other observed shape.
    match = re.search(r"using preset\s*[`'\"]?([A-Za-z]+)", blob)
    return match.group(1).lower() if match else None


def main() -> int:
    problems: list[str] = []

    if not has_mypy_section():
        problems.append(
            "pyproject.toml has no [tool.mypy] section. That section is "
            "pyrefly's configuration here, not leftovers from the mypy "
            "package removed in v4.169.32: its presence selects the "
            "`legacy` preset, and without it pyrefly drops to `basic`, "
            "which stops checking calls and assignments."
        )

    if PYREFLY_TOML.exists():
        problems.append(
            f"{PYREFLY_TOML.name} exists. A pyrefly config of its own "
            f"overrides the [tool.mypy] import and stops pyrefly printing "
            f"which preset it chose, so this guard can no longer measure "
            f"it -- verified: a pyrefly.toml with preset = \"basic\" was "
            f"reported as 'unmeasured' and passed. If a real pyrefly "
            f"config is wanted, prove the preset another way first and "
            f"teach this guard how."
        )

    preset = observed_preset()
    if preset is None and not PYREFLY_TOML.exists():
        print(
            "SKIP: pyrefly is not runnable here, so the preset could not be "
            "measured; only the [tool.mypy] section was checked. Never "
            "read this as 'the preset is fine'.",
            file=sys.stderr,
        )
    elif preset is not None and preset != REQUIRED_PRESET:
        problems.append(
            f"pyrefly resolved to the `{preset}` preset, not "
            f"`{REQUIRED_PRESET}`. `basic` reports fewer errors while "
            f"checking less -- it drops call and assignment checks. "
            f"Confirm what changed before touching the quality baseline."
        )

    if problems:
        print("PYREFLY PRESET FAILURES:", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        return 1

    measured = f"pyrefly reports `{preset}`" if preset else "preset unmeasured"
    print(f"OK: [tool.mypy] present, {measured}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
