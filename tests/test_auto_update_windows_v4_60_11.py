r"""v4.60.11: auto_update_windows mover must survive install paths that
contain ``(`` or ``)`` characters (e.g. ``arena-agent (2)\arena-agent``,
which browsers create when re-downloading an already-present zip).

The pre-v4.60.11 mover used ``if exist "SRC\*" ( robocopy ... ) else ( ... )``
blocks. Windows batch parses ``(...)`` blocks up-front, so a ``)`` inside
a path value closes the block early -> the mover silently exits before
any files are copied -> ``apply_update`` returns ``"swapped": null`` and
the bridge stays on the old version. This test guards against that
regression by asserting the generated ``.arena-update-apply.cmd`` uses
only ``if EXPR goto :label`` sequences for its control flow.
"""
from __future__ import annotations

from pathlib import Path

import pytest

# Import auto_update FIRST so _REPLACE_TARGETS is defined by the time
# auto_update_windows tries to reach back for it (circular import, but
# workable if the parent is loaded first).
from arena.admin import auto_update  # noqa: F401
from arena.admin.auto_update_windows import _write_windows_installer


@pytest.fixture
def paren_install_root(tmp_path):
    """Reproduce the actual bug: an install path with '(' and ')' in it."""
    root = tmp_path / "arena-agent (2)" / "arena-agent"
    root.mkdir(parents=True)
    payload = tmp_path / "payload" / "arena-agent"
    payload.mkdir(parents=True)
    # Populate a few known targets so the generated script has real
    # ``SRC`` paths to reference.
    (payload / "arena").mkdir()
    (payload / "arena" / "__init__.py").write_text("")
    (payload / "unified_bridge.py").write_text("")
    marker = tmp_path / "done.txt"
    return payload, root, marker


def test_generated_mover_uses_no_if_paren_blocks(paren_install_root):
    """No control-flow ``if ... (`` inside the generated mover — the whole
    reason the v4.60.11 rewrite exists is to avoid ``()`` blocks that get
    torn apart by ``)`` inside install paths."""
    payload, root, marker = paren_install_root
    script = _write_windows_installer(payload, root, marker)
    text = script.read_text(encoding="utf-8")
    # ``if <cond> goto :label`` is fine. ``if <cond> (`` is not.
    # We check by scanning lines: any line whose leading ``if`` keyword
    # ends with an open paren is the pattern we banned.
    offenders: list[tuple[int, str]] = []
    for i, line in enumerate(text.splitlines(), 1):
        stripped = line.strip().lower()
        if not stripped.startswith("if "):
            continue
        if stripped.endswith("("):
            offenders.append((i, line))
    assert not offenders, (
        "auto_update_windows mover still uses ``if ... (`` control-flow "
        "blocks; a ')' inside a path value will close them early:\n"
        + "\n".join(f"  L{ln}: {l!r}" for ln, l in offenders)
    )


def test_generated_mover_references_target_paths_verbatim(paren_install_root):
    payload, root, marker = paren_install_root
    script = _write_windows_installer(payload, root, marker)
    text = script.read_text(encoding="utf-8")
    # The paren-containing paths must appear verbatim in the generated
    # script (as targets of robocopy / copy commands).
    assert "arena-agent (2)" in text, (
        "install path with parens is not appearing in the mover output at all"
    )


def test_generated_mover_uses_disable_delayed_expansion(paren_install_root):
    """The mover must NOT enable delayed expansion — path values can
    contain ``!`` characters (Windows usernames occasionally do), and the
    mover's control flow deliberately relies on straight-line
    ``if EXPR goto`` sequences that don't need ``!VAR!`` references."""
    payload, root, marker = paren_install_root
    script = _write_windows_installer(payload, root, marker)
    text = script.read_text(encoding="utf-8").lower()
    assert "setlocal disabledelayedexpansion" in text, (
        "mover must ``setlocal disableDelayedExpansion`` so paths with '!' work"
    )


def test_generated_mover_writes_single_crlf_line_endings(paren_install_root):
    """Pre-v4.60.11 the mover was written via
    ``script.write_text('\\r\\n'.join(lines))``, and on Windows
    ``write_text`` converts ``\\n`` -> ``\\r\\n`` again, so line endings
    became ``\\r\\r\\n``. cmd tolerates that but it looks broken in every
    ``type`` dump. Use ``write_bytes`` with an explicit ``\\r\\n``."""
    payload, root, marker = paren_install_root
    script = _write_windows_installer(payload, root, marker)
    data = script.read_bytes()
    assert b"\r\r\n" not in data, "mover has \\r\\r\\n line endings (Python universal-newlines bug)"


def test_generated_mover_ends_with_relaunched_label(paren_install_root):
    payload, root, marker = paren_install_root
    script = _write_windows_installer(payload, root, marker)
    text = script.read_text(encoding="utf-8")
    # Must contain the ``:relaunched`` label so goto targets resolve.
    assert ":relaunched" in text
    # Must attempt Scheduled Task
    assert "schtasks /Run /TN" in text
