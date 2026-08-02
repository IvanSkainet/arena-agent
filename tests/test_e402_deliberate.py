"""The one remaining E402 is load bearing, and this proves it.

`arena/admin/auto_update.py` ends with a bottom-of-file import:

    from arena.admin.auto_update_windows import _write_windows_installer  # noqa: E402

Every other E402 in the tree was hoisted to the top during the debt cleanup.
This one cannot be: `auto_update_windows` imports `_REPLACE_TARGETS` back out
of `auto_update`, so moving the import up makes the cycle bite during module
initialisation.

A `# noqa` with a comment is a claim. This file turns it into a check: it
actually performs the hoist in a scratch copy and demands the import fail.
If someone later breaks the cycle (a good change), this test fails and tells
them the noqa is now removable — which is the right outcome, not a nuisance.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
TARGET = REPO / "arena" / "admin" / "auto_update.py"
PARTNER = REPO / "arena" / "admin" / "auto_update_windows.py"
LATE_IMPORT = "from arena.admin.auto_update_windows import _write_windows_installer"


def test_only_one_e402_remains_and_it_is_this_one():
    proc = subprocess.run(
        [sys.executable, "-m", "ruff", "check", "--select", "E402",
         "--output-format=concise", "arena", "tests"],
        cwd=REPO, capture_output=True, text=True,
    )
    # noqa keeps it out of the report; the point is that nothing ELSE crept in.
    assert proc.returncode == 0, proc.stdout


def test_the_late_import_is_still_marked_deliberate():
    src = TARGET.read_text(encoding="utf-8")
    assert LATE_IMPORT in src, "the late import vanished; update this gate"
    line = next(ln for ln in src.splitlines() if ln.startswith(LATE_IMPORT))
    assert "noqa: E402" in line, "the deliberate marker was dropped"
    # The reasoning must survive rewording, so match the invariant rather than
    # a sentence: the comment has to name the cycle's other half and say the
    # placement is intentional.
    assert "_REPLACE_TARGETS" in src, "the comment no longer names the cycle"
    assert "deliberate" in src.lower(), "the comment no longer says it is intentional"


def test_the_partner_module_still_imports_back():
    """The cycle's other half. If this changes, the noqa may be removable."""
    src = PARTNER.read_text(encoding="utf-8")
    assert "from arena.admin.auto_update import _REPLACE_TARGETS" in src


def test_hoisting_the_import_really_breaks(tmp_path):
    """Execute the counterfactual instead of asserting it in prose."""
    pkg_root = tmp_path / "pkg"
    shutil.copytree(REPO / "arena", pkg_root / "arena",
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))

    target = pkg_root / "arena" / "admin" / "auto_update.py"
    src = target.read_text(encoding="utf-8")
    line = next(ln for ln in src.splitlines() if ln.startswith(LATE_IMPORT))
    src = src.replace(line + "\n", "", 1)
    anchor = "from __future__ import annotations\n"
    idx = src.index(anchor) + len(anchor)
    target.write_text(src[:idx] + line.split("  # noqa")[0] + "\n" + src[idx:],
                      encoding="utf-8")

    probe = textwrap.dedent("""
        import sys
        sys.path.insert(0, sys.argv[1])
        try:
            import arena.admin.auto_update  # noqa: F401
        except ImportError as exc:
            print("IMPORTERROR:" + str(exc))
        else:
            print("IMPORTED-FINE")
    """)
    script = tmp_path / "probe.py"
    script.write_text(probe, encoding="utf-8")

    proc = subprocess.run([sys.executable, str(script), str(pkg_root)],
                          capture_output=True, text=True, timeout=120)
    out = proc.stdout.strip()
    if "IMPORTED-FINE" in out:
        pytest.fail(
            "Hoisting the import no longer fails -- the circular dependency is "
            "gone. Remove the `# noqa: E402` and this test, and hoist the "
            "import for real."
        )
    assert "IMPORTERROR:" in out, f"unexpected probe result: {out or proc.stderr[:300]}"
    assert "_REPLACE_TARGETS" in out
    assert "circular" in out or "partially initialized" in out


def test_the_symbol_is_actually_used_not_just_imported():
    """A late import kept only to satisfy a linter would be worse than the lint."""
    src = TARGET.read_text(encoding="utf-8")
    after = src.split(LATE_IMPORT, 1)[1]
    assert "_write_windows_installer" in after, (
        "the imported name is never referenced after the import"
    )
