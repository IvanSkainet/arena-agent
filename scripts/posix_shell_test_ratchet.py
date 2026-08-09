#!/usr/bin/env python3
"""Gate: a test must not shell out to `sh`/`bash` without skipping on Windows.

CI runs five `windows-latest` jobs. There is no `sh` there, and the
`bash` that `where` finds is a WSL stub that prints to stdout and exits
non-zero. So a test that spawns either passes on three Linux jobs and
fails on five Windows ones -- a red build produced entirely by the test,
not by the code under test.

Three times in eleven releases:

  * v4.169.9  -- `env={"PATH": "/usr/bin:/bin"}` dropped SYSTEMROOT and
    CPython could not start at all.
  * v4.169.15 -- a doctor test assumed the Linux branch and compared
    against the wrong string on Windows.
  * v4.169.19 -- a boot-script test ran `sh` to exercise a port check
    that is one `connect_ex` call.

Every one was a platform assumption baked into a *test* rather than into
the code being tested, and every one was found by CI rather than before
it. Hence a gate.

Skipping is allowed and is often right: mark it with
`@pytest.mark.skipif(... sys.platform == "win32" ...)` or gate it on
`shutil.which(...)`. What is not allowed is spawning a POSIX shell
unconditionally.
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
TESTS = REPO_ROOT / "tests"
SHELLS = {"sh", "bash", "dash", "zsh", "/bin/sh", "/bin/bash"}
MIN_FILES_SCANNED = 50

# A detector that silently scans nothing reports OK forever -- caught by
# sabotage in v4.169.7 and pinned ever since.


def _spawns_shell(node: ast.Call) -> str | None:
    """The shell name when this call launches one, else None."""
    func = ast.unparse(node.func)
    if not func.startswith(("subprocess.", "asyncio.create_subprocess", "os.spawn")):
        return None
    if not node.args:
        return None
    first = node.args[0]
    if isinstance(first, ast.Constant) and isinstance(first.value, str):
        return first.value if first.value in SHELLS else None
    if isinstance(first, (ast.List, ast.Tuple)) and first.elts:
        head = first.elts[0]
        if isinstance(head, ast.Constant) and isinstance(head.value, str):
            return head.value if head.value in SHELLS else None
    return None


def _is_guarded(text: str) -> bool:
    """True when the file gates itself on the platform or the binary."""
    markers = (
        'sys.platform == "win32"',
        "sys.platform == 'win32'",
        'sys.platform != "win32"',
        "shutil.which",
        "skipif",
    )
    return any(marker in text for marker in markers)


def violations() -> tuple[list[str], int]:
    found: list[str] = []
    scanned = 0
    if not TESTS.is_dir():
        raise SystemExit(f"posix shell ratchet: tests directory missing: {TESTS}")
    for path in sorted(TESTS.glob("test_*.py")):
        scanned += 1
        text = path.read_text(encoding="utf-8")
        try:
            tree = ast.parse(text)
        except SyntaxError:  # pragma: no cover -- ruff catches these first
            continue
        if _is_guarded(text):
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            shell = _spawns_shell(node)
            if shell:
                found.append(
                    f"{path.name}:{node.lineno}: spawns {shell!r} with no Windows "
                    f"skip; five windows-latest jobs have no POSIX shell"
                )
    return found, scanned


def main() -> int:
    found, scanned = violations()
    if scanned < MIN_FILES_SCANNED:
        print(f"posix shell ratchet: FAIL -- scanned only {scanned} test files "
              f"(expected at least {MIN_FILES_SCANNED}); the scan is broken")
        return 1
    if found:
        print("posix shell ratchet: FAIL")
        for line in found:
            print(f"  {line}")
        print()
        print("  Either exercise the logic directly in Python, or guard the test")
        print('  with @pytest.mark.skipif(sys.platform == "win32", ...).')
        return 1
    print(f"posix shell ratchet: OK ({scanned} test files)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
