"""Every Windows helper script (``*.bat``) must have a POSIX sibling (``*.sh``).

The bridge shipped a ``start.bat`` from day one, but ``start.sh`` was
missing for a long time. This test blocks that regression from ever
returning.

If a truly platform-specific script needs to exist without a sibling,
add its name to ``BAT_ONLY_ALLOWLIST`` with a comment explaining why.
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Batch files that intentionally have no POSIX equivalent.
BAT_ONLY_ALLOWLIST: set[str] = set()


def test_every_bat_has_sh_sibling():
    missing: list[str] = []
    for bat in sorted(ROOT.glob("*.bat")):
        if bat.name in BAT_ONLY_ALLOWLIST:
            continue
        sibling = bat.with_suffix(".sh")
        if not sibling.exists():
            missing.append(f"{bat.name} -> expected sibling {sibling.name}")
    assert not missing, (
        "GNU/Linux/macOS users need parity with Windows scripts. "
        "Create the missing .sh files (POSIX bash, `#!/usr/bin/env bash`, "
        "`set -euo pipefail`).\n"
        + "\n".join(missing)
    )


def test_sh_scripts_are_executable_bash():
    """Every ``*.sh`` in the repo root must start with a bash shebang."""
    offenders: list[str] = []
    for sh in sorted(ROOT.glob("*.sh")):
        with sh.open("rb") as fh:
            first_line = fh.readline().decode("utf-8", "replace").strip()
        if first_line not in {
            "#!/usr/bin/env bash",
            "#!/bin/bash",
        }:
            offenders.append(f"{sh.name}: shebang was {first_line!r}")
    assert not offenders, "\n".join(offenders)
