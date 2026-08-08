#!/usr/bin/env python3
"""Gate: nothing but ``key=value`` may be written to ``$GITHUB_OUTPUT``.

The version-badge workflow redirected an entire ``python3`` heredoc into
``$GITHUB_OUTPUT``. The script printed ``skip=true`` -- fine -- and then a
``::warning::`` annotation, which landed in the output file too. GitHub
rejects it:

    ##[error]Unable to process file command 'output' successfully.
    ##[error]Invalid format '::warning::badge stayed at 4.169.6; ...'

So the anti-race guard worked correctly and then failed the job for
saying so. Two releases in a row shipped with a red badge run that had to
be explained away by hand, which is exactly how a real failure gets
waved through.

The rule this enforces is narrow and mechanical: a ``run:`` step must not
redirect a whole interpreter block into ``$GITHUB_OUTPUT``. Write the
key=value lines explicitly (open the file, append) and leave stdout free
for logs and annotations.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = REPO_ROOT / ".github" / "workflows"

# `python3 - <<'EOF' >> "$GITHUB_OUTPUT"` and friends: a heredoc-fed
# interpreter whose *whole* stdout is redirected at the output file.
HEREDOC_TO_OUTPUT = re.compile(
    r"<<-?\s*'?[A-Za-z_][A-Za-z0-9_]*'?[^\n]*>>?\s*\"?\$\{?GITHUB_OUTPUT\}?\"?"
)
# The same shape with the redirect written before the heredoc marker.
OUTPUT_THEN_HEREDOC = re.compile(
    r">>?\s*\"?\$\{?GITHUB_OUTPUT\}?\"?[^\n]*<<-?\s*'?[A-Za-z_][A-Za-z0-9_]*'?"
)

MIN_FILES_SCANNED = 5


def violations() -> tuple[list[str], int]:
    found: list[str] = []
    scanned = 0
    if not WORKFLOWS.is_dir():
        raise SystemExit(f"github output ratchet: workflows directory missing: {WORKFLOWS}")
    for path in sorted(WORKFLOWS.glob("*.y*ml")):
        scanned += 1
        rel = path.relative_to(REPO_ROOT).as_posix()
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if HEREDOC_TO_OUTPUT.search(line) or OUTPUT_THEN_HEREDOC.search(line):
                found.append(
                    f"{rel}:{lineno}: an interpreter heredoc is redirected into "
                    f"$GITHUB_OUTPUT; a stray log line there fails the step"
                )
    return found, scanned


def main() -> int:
    found, scanned = violations()
    if scanned < MIN_FILES_SCANNED:
        print(f"github output ratchet: FAIL -- scanned only {scanned} workflow files "
              f"(expected at least {MIN_FILES_SCANNED}); the scan is broken")
        return 1
    if found:
        print("github output ratchet: FAIL")
        for line in found:
            print(f"  {line}")
        print()
        print("  Append key=value lines explicitly instead:")
        print('    with open(os.environ["GITHUB_OUTPUT"], "a") as fh: fh.write(f"k={v}\\n")')
        return 1
    print(f"github output ratchet: OK ({scanned} workflow files)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
