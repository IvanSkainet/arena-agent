r"""v4.60.9: install.bat must survive paths containing '(' or ')'.

Windows batch parses parenthesised blocks up-front, so ``if exist "%X%\..." (``
followed by a body that also mentions ``%X%`` breaks when %X% expands to
a value like ``C:\Users\...\arena-agent (1)\arena-agent``: the ``)`` from
``(1)`` closes the block early and the rest of the body leaks into the
enclosing scope.

The fix is delayed expansion — reference !BRIDGE_DIR!/!TOKEN_FILE!/etc.
so the value is inserted AFTER block parsing.
"""
from __future__ import annotations

import re
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
INSTALL_BAT = REPO_ROOT / "install.bat"


def _read() -> str:
    # install.bat is CRLF in the repo but tolerate either.
    return INSTALL_BAT.read_text(encoding="utf-8", errors="replace")


def test_install_bat_uses_delayed_expansion_for_derived_paths():
    """Every derived path variable must be referenced via !VAR!, not %VAR%,
    outside of the initial ``set "VAR=..."`` line. Otherwise a ')' inside
    the value breaks parenthesised blocks."""
    src = _read()
    # Skip the two documented exceptions where slice syntax is used.
    problem_vars = ("BRIDGE_DIR", "TOKEN_FILE", "REQ_FILE", "PYTHON")
    lines = src.splitlines()
    offenders: list[tuple[int, str, str]] = []
    for lineno, line in enumerate(lines, 1):
        stripped = line.strip()
        if stripped.startswith("REM") or stripped.startswith("::"):
            continue
        # Legitimate ``set "BRIDGE_DIR=%~dp0"`` / slice ``%BRIDGE_DIR:~-1%``
        if 'set "BRIDGE_DIR=%~dp0"' in line:
            continue
        if 'BRIDGE_DIR:~' in line:
            continue
        for var in problem_vars:
            if f"%{var}%" in line:
                offenders.append((lineno, var, line[:200]))
    assert not offenders, (
        f"install.bat still uses %VAR% for path variables that may contain '(':\n"
        + "\n".join(f"  L{ln}: %{v}% -> {ctx!r}" for ln, v, ctx in offenders)
    )


def test_install_bat_declares_enabledelayedexpansion():
    """Delayed expansion must be enabled at the top of the script."""
    src = _read()
    # First 5 non-empty non-comment lines must contain setlocal enabledelayedexpansion.
    for line in src.splitlines()[:10]:
        if "setlocal enabledelayedexpansion" in line.lower():
            return
    raise AssertionError("install.bat missing `setlocal enabledelayedexpansion`")


def test_install_bat_parenthesis_balance():
    """Ignoring quoted regions and REM/:: comments, the file's ``(`` and
    ``)`` must balance to zero."""
    src = _read()
    depth = 0
    for lineno, line in enumerate(src.splitlines(), 1):
        stripped = line.strip()
        if stripped.startswith("REM") or stripped.startswith("::"):
            continue
        in_quote = False
        for ch in line:
            if ch == '"':
                in_quote = not in_quote
                continue
            if in_quote:
                continue
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
        assert depth >= 0, (
            f"install.bat has an unmatched closing ')' at or before line "
            f"{lineno}: {line.rstrip()!r}"
        )
    assert depth == 0, f"install.bat parenthesis depth ends at {depth}, expected 0"


def test_install_bat_warns_about_parens_in_path():
    """The v4.60.9 diagnostic banner must be present so operators
    learn what to look for if things do go wrong."""
    src = _read()
    assert (
        re.search(r"Install directory contains parentheses", src) is not None
    ), "install.bat missing the v4.60.9 parenthesis diagnostic banner"
