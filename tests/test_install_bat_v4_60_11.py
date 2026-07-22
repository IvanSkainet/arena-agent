r"""v4.60.11 install.bat regression guards for the specific breakages
Ivan observed in the v4.60.10 install into ``arena-agent (3)\arena-agent``.

Two things went wrong there:
1. ``echo ... binary (~300MB) if you plan to use ...`` inside an
   ``if ... (`` block. The unescaped ``(`` in ``(~300MB)`` opened a
   phantom nested block that closed on the ``)`` inside ``(~300MB)``,
   leaving the outer ``) else (`` unmatched. cmd printed
   "Непредвиденное появление: if." and bailed.
2. ``echo ... Wacatac.B^!ml`` — a single caret in front of ``!`` is not
   enough under ``enabledelayedexpansion``; cmd still eats ``!m!`` as
   an empty variable expansion. The runtime output was ``Wacatac.Bml``.
   Correct escape is ``^^!``.
"""
from __future__ import annotations

import re
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
INSTALL_BAT = REPO_ROOT / "install.bat"


def _read() -> str:
    return INSTALL_BAT.read_text(encoding="utf-8", errors="replace")


def test_wacatac_uses_double_caret_bang():
    src = _read()
    assert "Wacatac.B^^!ml" in src, (
        "install.bat must escape the '!' in Wacatac.B!ml as '^^!' — a single "
        "caret is silently stripped by enabledelayedexpansion, producing "
        "'Wacatac.Bml' in Ivan's terminal (v4.60.10 field observation)."
    )
    # And must NOT contain the single-caret form (would round-trip incorrectly)
    residue = src.replace("Wacatac.B^^!ml", "")
    assert "Wacatac.B^!ml" not in residue and "Wacatac.B!ml" not in residue, (
        "install.bat still contains a single-caret or unescaped Wacatac.B!ml"
    )


def test_python_not_found_uses_double_caret_bang():
    src = _read()
    assert "Python not found^^!" in src


_BLOCK_OPENER_KEYWORDS = ("if", "for", "else", "do", "(")


def _parse_depth_by_line(src: str) -> dict[int, int]:
    """Return {lineno: depth_at_start} using cmd.exe's real block rules.

    cmd only treats ``(`` as a block-opener when it terminates one of
    the constructs that legitimately introduce a block: ``if <cond> (``,
    ``for <spec> do (``, ``else (``, or a bare ``(`` on its own line.
    A ``(`` mid-echo-argument is just a literal parenthesis.

    Similarly, ``)`` only closes a block if it's the first non-whitespace
    token on the line, or the last token of an ``if ( ... ) else`` /
    ``) else (`` bridge. Any other ``)`` is just literal text.
    """
    depth = 0
    depths: dict[int, int] = {}
    for i, line in enumerate(src.splitlines(), 1):
        stripped = line.strip()
        depths[i] = depth
        if stripped.lower().startswith("rem") or stripped.startswith("::"):
            continue
        # Block-close only counts if line starts with ``)`` (optionally
        # with ``)`` followed by ``else`` bridge or ``)`` alone).
        if stripped.startswith(")"):
            depth -= 1
            # ``) else (`` decreases then increases
            if "else" in stripped and stripped.endswith("("):
                depth += 1
            continue
        # Block-open only if the line ends with an unquoted ``(`` AND
        # begins with an if/for/else/do keyword (or is a bare ``(``).
        low = stripped.lower()
        opens_block = False
        if low.endswith("(") and not low.endswith("^("):
            for kw in ("if ", "for ", "else ", "else(", "do ", "do("):
                if low.startswith(kw) or low == "else(" or low == kw.rstrip():
                    opens_block = True
                    break
            if low == "(":
                opens_block = True
        if opens_block:
            depth += 1
    return depths


def test_no_unescaped_parens_in_echo_inside_blocks():
    r"""Any ``echo`` line that runs inside a ``(...)`` block must have
    its literal ``(`` and ``)`` escaped as ``^(`` and ``^)``. Otherwise
    cmd tears the enclosing block apart on the unescaped ``)``.

    We flag unescaped parens on ``echo`` lines where the parenthesis
    depth at the start of the line is >0. Escape sequences ``^(`` and
    ``^)`` are counted as safe by the analyser above.
    """
    src = _read()
    depths = _parse_depth_by_line(src)
    offenders: list[tuple[int, str]] = []
    for i, line in enumerate(src.splitlines(), 1):
        stripped = line.strip()
        low = stripped.lower()
        if not (low.startswith("echo ") or low == "echo"):
            continue
        if depths[i] == 0:
            continue
        # Count unescaped ( and ) in the echo argument
        prev = ""
        unesc_open = 0; unesc_close = 0
        for c in line:
            if c == "(" and prev != "^":
                unesc_open += 1
            elif c == ")" and prev != "^":
                unesc_close += 1
            prev = c
        if unesc_open or unesc_close:
            offenders.append((i, line))
    assert not offenders, (
        "install.bat has echo lines with unescaped '(' or ')' inside "
        "an enclosing (...) block. cmd will tear the enclosing block "
        "apart on the unescaped ')':\n"
        + "\n".join(f"  L{ln} depth={depths[ln]}: {l.rstrip()[:120]}" for ln, l in offenders)
    )
