#!/usr/bin/env python3
"""Gate: CI must not install Python packages without hash pinning.

Scorecard flagged `.github/workflows/ci.yml` with
`pipCommand not pinned by hash` (score 7, medium). It was right, and it
was pointing at one line out of eight: two jobs ran `pip install pytest`
and `pip install hypothesis`, and six more ran
`pip install -r requirements.txt`, which carries floors
(`aiohttp>=3.14.1`) rather than pins. Every one of those resolved to
whatever PyPI served that minute.

That matters more here than in most projects. This repository ships a
tool that executes commands on the operator's machine, and CI is what
decides a release is fit to publish. An unpinned install is a place
where a swapped package changes what the tests run against, with nothing
turning red.

Every package involved was already hash-pinned in
`requirements-ci.lock`, so the fix made the commands shorter as well as
safer.

Allowed:

  * ``pip install --require-hashes -r <lock>`` -- the intended form.
  * ``pip install --upgrade pip`` -- bootstrapping pip itself.
  * ``pip install --no-deps <local path or wheel>`` -- installing this
    project's own artefact, which has no registry to be swapped in.
  * ``pip install -e .`` with ``--no-deps`` -- same reasoning.

Refused: anything that names a package or a non-lock requirements file
and lets the resolver decide.

Shell line continuations are joined before matching. Reading a workflow
line by line, as this gate first did, splits

    python -m pip install \\
      --require-hashes -r requirements-guarddog.txt

into a first line that has no ``--require-hashes`` on it, and the gate
failed a compliant install (#231: sixteen red checks in #228, all
pointing at a command that was already correct). The reverse error is
the dangerous one, so joining is deliberately conservative: a comment
line is never joined into the command below it, because
``# note \\`` followed by ``pip install evil`` would otherwise fold into
a single line starting with ``#`` and be skipped as prose.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = REPO_ROOT / ".github" / "workflows"
MIN_FILES_SCANNED = 5

_PIP_INSTALL = re.compile(r"\bpip\s+install\b")

# A lock file is the only requirements file that may be installed
# without --require-hashes being suspicious, and even then we demand the
# flag; this just recognises the filename for a clearer message.
_LOCK_FILE = re.compile(r"requirements[\w.-]*\.lock")


def _is_allowed(line: str) -> bool:
    if "--require-hashes" in line:
        return True
    # Bootstrapping pip/setuptools/wheel themselves: there is no lock
    # that can pin the installer before the installer exists.
    if re.search(r"pip\s+install\s+(--upgrade\s+)?(pip|setuptools|wheel)\b", line):
        return True
    # Installing our own build output or source tree, no registry
    # resolution involved.
    if "--no-deps" in line:
        return True
    return False


def logical_lines(text: str) -> list[tuple[int, str]]:
    """Yield (line number, command) with shell continuations joined.

    The line number is that of the *first* physical line, so a failure
    message points at where the command starts rather than at the
    fragment that happened to carry the offending token.

    A comment is never used as the head of a continuation. In shell a
    ``#`` comment ends at the newline regardless of a trailing
    backslash, so folding the next line into it would hide a real
    command behind a ``#`` this gate skips.
    """
    out: list[tuple[int, str]] = []
    pending_no: int | None = None
    pending: list[str] = []
    for lineno, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if pending:
            pending.append(line.removesuffix("\\").strip() if line.endswith("\\") else line)
            if not line.endswith("\\"):
                out.append((pending_no or lineno, " ".join(pending)))
                pending, pending_no = [], None
            continue
        if line.startswith("#"):
            out.append((lineno, line))
            continue
        if line.endswith("\\"):
            pending_no = lineno
            pending = [line.removesuffix("\\").strip()]
            continue
        out.append((lineno, line))
    if pending:
        # Trailing backslash at end of file: keep what we have rather
        # than dropping a command the scan would otherwise never see.
        out.append((pending_no or len(text.splitlines()), " ".join(pending)))
    return out


def violations() -> tuple[list[str], int]:
    found: list[str] = []
    scanned = 0
    if not WORKFLOWS.is_dir():
        raise SystemExit(f"pinned pip ratchet: workflows directory missing: {WORKFLOWS}")
    for path in sorted(WORKFLOWS.glob("*.y*ml")):
        scanned += 1
        rel = path.relative_to(REPO_ROOT).as_posix()
        for lineno, line in logical_lines(path.read_text(encoding="utf-8")):
            # Comments explain the history; three releases in a row a
            # gate has flagged its own prose, so skip them explicitly.
            if line.startswith("#"):
                continue
            # `- name: Safe pip install` is a step title, not a command.
            # A detector that cannot tell a label from an invocation
            # produces noise, and noise is how a real finding gets
            # scrolled past.
            if re.match(r"-?\s*name\s*:", line):
                continue
            # Socket Firewall wraps the install *to test* that its
            # blocking works; that step deliberately attempts an
            # unpinned resolve and watches the firewall stop it.
            #
            # Narrowed after sabotage: a bare `startswith("sfw ")` let
            # `sfw pip install evil-package` through from any workflow.
            # The exemption is for one known file installing one known
            # generated file, not for the prefix.
            if line == "sfw pip install -r runtime-reqs.txt":
                continue
            if not _PIP_INSTALL.search(line):
                continue
            if _is_allowed(line):
                continue
            hint = ("use a lock file" if not _LOCK_FILE.search(line)
                    else "add --require-hashes")
            found.append(f"{rel}:{lineno}: unpinned install -- {hint}\n      {line[:100]}")
    return found, scanned


def main() -> int:
    found, scanned = violations()
    if scanned < MIN_FILES_SCANNED:
        print(f"pinned pip ratchet: FAIL -- scanned only {scanned} workflow files "
              f"(expected at least {MIN_FILES_SCANNED}); the scan is broken")
        return 1
    if found:
        print("pinned pip ratchet: FAIL")
        for line in found:
            print(f"  {line}")
        print()
        print("  python -m pip install --require-hashes -r requirements-ci.lock")
        return 1
    print(f"pinned pip ratchet: OK ({scanned} workflow files)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
