r"""v4.60.10: install.bat regression guards for delayed-expansion escaping
and Camoufox auto-install.

Under ``setlocal enabledelayedexpansion`` cmd.exe treats ``!name!`` as a
variable reference. Any literal ``!`` inside an ``echo`` argument gets
eaten (or, worse, expands to an empty variable value, silently mangling
the text). The last-mile symptom in Ivan's terminal was:

    (Trojan:Win32/Wacatac.Bml)     <-- expected: Wacatac.B!ml

cmd swallowed ``!m!`` as ``%m%`` -> empty. Escape with ``^!``.

Also verifies the v4.60.10 Camoufox auto-install branch is wired up so
that BrowserAct stealth mode works out of the box, not just prints a
manual command.
"""
from __future__ import annotations

import re
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
INSTALL_BAT = REPO_ROOT / "install.bat"


def _read() -> str:
    return INSTALL_BAT.read_text(encoding="utf-8", errors="replace")


def _echo_lines(src: str) -> list[tuple[int, str]]:
    out: list[tuple[int, str]] = []
    for lineno, line in enumerate(src.splitlines(), 1):
        # Match ``echo`` at start (any indent) but skip ``echo.``, ``echo off``,
        # and ``echo`` inside comments.
        stripped = line.strip()
        if stripped.lower().startswith("rem") or stripped.startswith("::"):
            continue
        low = stripped.lower()
        if low.startswith("echo ") or low == "echo":
            out.append((lineno, line))
    return out


def test_echo_lines_do_not_contain_unescaped_bang_literals():
    r"""Any ``!`` in an ``echo`` argument must be either part of a
    ``!VAR!`` delayed-expansion reference or escaped as ``^!``.
    A bare ``!`` mid-word is eaten by cmd and silently mangles the text.
    """
    src = _read()
    offenders: list[tuple[int, str]] = []
    for lineno, line in _echo_lines(src):
        # Strip legitimate !NAME! variable expansions
        stripped = re.sub(r"!\w+!", "", line)
        # Strip escape sequences ``^!``
        stripped = stripped.replace("^!", "")
        if "!" in stripped:
            offenders.append((lineno, line))
    assert not offenders, (
        "install.bat has ``echo`` lines with unescaped literal '!' that "
        "would be silently eaten by delayed expansion:\n"
        + "\n".join(f"  L{ln}: {l.rstrip()[:120]}" for ln, l in offenders)
    )


def test_wacatac_reference_is_correctly_escaped():
    """The Windows Defender false-positive advisory must display the
    canonical malware family name ``Wacatac.B!ml`` (not ``Wacatac.Bml``).

    v4.60.11: single-caret ``^!`` is not enough — cmd still eats ``!m!``
    as an empty variable expansion under enabledelayedexpansion. The
    correct escape is ``^^!``. See tests/test_install_bat_v4_60_11.py
    for the strict form; this test just asserts *some* escape is present.
    """
    src = _read()
    assert "Wacatac.B^^!ml" in src or "Wacatac.B^!ml" in src, (
        "install.bat missing an escape for the '!' in Wacatac.B!ml"
    )
    # If a single-caret escape is present, v4.60.11's stricter guard
    # (test_wacatac_uses_double_caret_bang) will fail loudly.
    # If a raw unescaped form is present, both guards fire.
    raw = src.replace("Wacatac.B^^!ml", "").replace("Wacatac.B^!ml", "")
    assert "Wacatac.B!ml" not in raw, (
        "install.bat still contains a raw ``Wacatac.B!ml`` (unescaped '!')"
    )


def test_camoufox_branch_attempts_uv_tool_install():
    """v4.60.10: when camoufox is missing, install.bat must attempt an
    automatic ``uv tool install --with camoufox`` rather than just
    printing a manual hint."""
    src = _read()
    # Grab the Camoufox section (between the marker and the ``:camoufox_done``
    # LABEL — not any ``goto :camoufox_done`` earlier in the section).
    m = re.search(
        r"REM --- Camoufox ---(.*?)^:camoufox_done\b",
        src, re.DOTALL | re.MULTILINE,
    )
    assert m, "install.bat missing Camoufox section (marker or label)"
    section = m.group(1)
    assert "uv tool install" in section and "--with camoufox" in section, (
        "Camoufox section does not attempt automatic install via "
        "``uv tool install --with camoufox`` -- it only prints a manual hint."
    )
    # And it must gate on ``where uv`` so systems without uv still get
    # a clean fallback.
    assert re.search(r"where uv\b", section), (
        "Camoufox section must probe ``where uv`` before running the tool "
        "install so systems without uv still print a manual hint."
    )


def test_python_not_found_bang_is_escaped():
    """Ivan's terminal never triggered this branch, but the same
    delayed-expansion eater lurks in the Python-not-found error banner.

    v4.60.11: accept either single or double-caret escape here — the
    v4.60.11-specific guard requires the double form. This test just
    asserts some escape is present.
    """
    src = _read()
    assert "Python not found^^!" in src or "Python not found^!" in src, (
        "install.bat 'Python not found' branch still has a bare '!' at the "
        "end that would be silently eaten by delayed expansion"
    )
