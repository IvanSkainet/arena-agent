"""v4.42.0 tests that desktop OCR + screenshot use secure
temp-file creation (audit hardening #3).

Pre-v4.42.0 both used ``tempfile.mktemp()`` which is TOCTOU-
racy: an attacker with local access to the same machine could
predict the name (``arena_ocr_<random>.png``) and pre-create a
symlink at the path, redirecting the subsequent write to any
file the bridge user could touch.

v4.42.0 changes:

* OCR uses ``NamedTemporaryFile(delete=False)`` which is
  atomic O_EXCL create.
* Screenshot uses ``mkdtemp()`` and writes inside the per-
  invocation 0o700 directory -- screenshot CLIs
  (spectacle/grim/scrot) need to create the file themselves
  so we can't use NamedTemporaryFile there; the parent-dir
  approach prevents a co-tenant from planting a symlink.
"""
from __future__ import annotations

import inspect

from arena.desktop import ocr, screenshot


def _has_active_mktemp_call(src: str) -> bool:
    """Look for a real ``tempfile.mktemp(`` call in ``src``,
    ignoring occurrences inside comment lines (``# ...``) --
    the v4.42.0 fix intentionally names the deprecated API in
    rationale comments so future readers understand why the
    change happened."""
    for line in src.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        # Trim the inline-comment tail so ``x = 1  # tempfile.mktemp``
        # does not trip the check.
        code = stripped.split("#", 1)[0]
        if "tempfile.mktemp(" in code:
            return True
    return False


def test_ocr_module_does_not_call_mktemp():
    """Regression guard: mktemp() must never come back to this
    file. Rationale comments naming the deprecated API are
    allowed; only real function calls are rejected."""
    src = inspect.getsource(ocr)
    assert not _has_active_mktemp_call(src), (
        "arena/desktop/ocr.py must not call tempfile.mktemp() -- "
        "it is TOCTOU-racy; use NamedTemporaryFile(delete=False)"
    )
    assert "NamedTemporaryFile" in src, (
        "arena/desktop/ocr.py should use tempfile.NamedTemporaryFile "
        "for the OCR staging file"
    )


def test_screenshot_module_does_not_call_mktemp():
    src = inspect.getsource(screenshot)
    assert not _has_active_mktemp_call(src), (
        "arena/desktop/screenshot.py must not call tempfile.mktemp() -- "
        "it is TOCTOU-racy; use mkdtemp() and write inside the dir"
    )
    assert "mkdtemp" in src, (
        "arena/desktop/screenshot.py should use tempfile.mkdtemp "
        "for the screenshot staging directory"
    )


def test_screenshot_has_cleanup_helper():
    """The rmtree cleanup must survive refactors -- an orphaned
    per-invocation directory in /tmp adds up fast on a busy
    bridge."""
    assert hasattr(screenshot, "_rm_tmp_dir"), (
        "arena/desktop/screenshot.py should expose _rm_tmp_dir()"
    )
