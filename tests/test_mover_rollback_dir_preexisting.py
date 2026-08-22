"""An existing rollback directory must not abort the update.

Found on the operator's Windows host while installing v4.169.49. The
mover logged, in this order::

    bridge exited, starting copy
    rollback directory unavailable
    ERROR copy failed, restoring rollback snapshot

No file was ever copied. The bridge came back on the *old* version and
the release sat on disk unused.

The cause is one line of cmd.exe::

    mkdir "<backup>" 2>NUL
    if not errorlevel 1 goto :rollback_dir_ready

``mkdir`` sets errorlevel 1 when the directory already exists, so a
pre-existing snapshot directory -- left by an earlier attempt, or by the
apply that prepared this very deployment id -- is read as "cannot make a
rollback" and the mover fail-closes. The deployment id is derived from
the *previous* version and its zip digest, so a retried update of the
same version reuses the same path by construction. The second attempt
could never succeed.

This is the same lesson v4.169.21 learned about ``schtasks``: an exit
code describing *how the call went* is not the observable we care about.
What matters is whether the directory is there afterwards, so that is
what the mover now checks.
"""
from __future__ import annotations

import pathlib
import tempfile

import pytest

import arena.admin.auto_update as _au  # noqa: F401 -- breaks a circular import
from arena.admin.auto_update_windows import _write_windows_installer


def _script(backup_root: pathlib.Path | None) -> str:
    root = pathlib.Path(tempfile.mkdtemp())
    (root / "src").mkdir()
    (root / "dst").mkdir()
    script = _write_windows_installer(
        root / "src", root / "dst", root / "done.txt",
        backup_root=backup_root,
    )
    return script.read_text(encoding="utf-8", errors="replace")


@pytest.fixture
def backup_script() -> str:
    root = pathlib.Path(tempfile.mkdtemp())
    return _script(root / "backups" / "deployments" / "4.169.48-b88f7220db12b83d")


def test_mkdir_errorlevel_is_not_the_rollback_gate(backup_script: str) -> None:
    """The exact line that bricked the v4.169.49 install must be gone."""
    assert "if not errorlevel 1 goto :rollback_dir_ready" not in backup_script, (
        "mkdir's errorlevel is still the gate: a rollback directory that "
        "already exists will abort the update again"
    )


def test_rollback_readiness_is_decided_by_the_directory_existing(
    backup_script: str,
) -> None:
    """Gate on the observable -- the directory -- not on the call's exit code."""
    assert "if exist" in backup_script
    # Absence of the directory routes to the "unavailable" failure, and that
    # decision is an existence test rather than a call's exit code.
    guard = next(
        line for line in backup_script.splitlines()
        if line.endswith("goto :rollback_dir_unavailable")
        and not line.startswith(":")
    )
    assert guard.startswith('if not exist "'), (
        f"readiness is not gated on directory existence: {guard!r}"
    )
    assert guard.endswith('\\." goto :rollback_dir_unavailable'), (
        rf"must use the `\.` form, which is also true for an empty dir: {guard!r}"
    )


def test_a_stale_snapshot_is_cleared_so_the_backup_is_not_a_mixture(
    backup_script: str,
) -> None:
    """A leftover snapshot must not be merged with the one we take now."""
    clear = backup_script.index('rmdir /S /Q "')
    make = backup_script.index('mkdir "')
    first_robocopy = backup_script.index("robocopy")
    assert clear < first_robocopy, "stale snapshot is never cleared"
    assert make < first_robocopy
    assert clear < backup_script.index(":rollback_dir_ready")


def test_the_unavailable_path_still_exists_for_a_genuine_failure(
    backup_script: str,
) -> None:
    """Fail-closed behaviour is preserved when the directory truly cannot exist."""
    assert "rollback directory unavailable" in backup_script
    unavailable = backup_script.index("rollback directory unavailable")
    assert "goto :copy_failed" in backup_script[unavailable:]


def test_no_parenthesised_if_block_was_introduced(backup_script: str) -> None:
    """v4.60.11: a path like ``arena-agent (2)`` closes an ``if (...)`` early."""
    for line in backup_script.splitlines():
        stripped = line.strip()
        if stripped.lower().startswith("if ") and stripped.endswith("("):
            pytest.fail(f"parenthesised if block reintroduced: {line!r}")


def test_backupless_movers_are_untouched() -> None:
    """A mover with no rollback root must not grow a rollback gate."""
    assert ":rollback_dir_ready" not in _script(None)


def test_a_snapshot_that_could_not_be_purged_aborts_instead_of_mixing(
    backup_script: str,
) -> None:
    """`rmdir` suppresses its errors, so "it exists" does not mean "it is ours".

    A locked file leaves the old snapshot in place; backing up on top of it
    produces a rollback tree that is a mixture of two attempts. Raised in
    review of this change and reproduced here as a requirement: the mover
    must confirm the directory is empty before claiming it.
    """
    assert "stale rollback snapshot could not be purged" in backup_script
    dirty = backup_script.index(":rollback_dir_dirty")
    ready = backup_script.index(":rollback_dir_ready")
    first_robocopy = backup_script.index("robocopy")
    assert dirty < first_robocopy and ready < first_robocopy
    # The emptiness check has to happen before we declare the backup ours.
    assert "dir /b /a" in backup_script
    assert backup_script.index("dir /b /a") < ready


def test_the_two_failure_modes_are_reported_distinctly(backup_script: str) -> None:
    """"Cannot create" and "cannot purge" are different operator problems."""
    assert "rollback directory unavailable" in backup_script
    assert ":rollback_dir_unavailable" in backup_script
    assert backup_script.count("goto :copy_failed") >= 2
