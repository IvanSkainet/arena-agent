"""T55 platform mover parity for retained rollback evidence."""
from __future__ import annotations

from pathlib import Path

from arena.admin import auto_update
from arena.admin.auto_update_windows import _write_windows_installer
from arena.admin.deployment_provenance import DEPLOYED_PROVENANCE


def test_posix_swap_retains_exact_previous_tree_and_publishes_provenance_last(tmp_path: Path) -> None:
    payload = tmp_path / "payload"
    install = tmp_path / "install"
    backup = install / "backups" / "deployments" / "4.169.99-old"
    staged = tmp_path / "staging" / DEPLOYED_PROVENANCE
    (payload / "arena").mkdir(parents=True)
    (payload / "arena" / "new.py").write_text("new", encoding="utf-8")
    (install / "arena").mkdir(parents=True)
    (install / "arena" / "old.py").write_text("old", encoding="utf-8")
    (install / DEPLOYED_PROVENANCE).write_text("old provenance", encoding="utf-8")
    staged.parent.mkdir()
    staged.write_text("new provenance", encoding="utf-8")

    result = auto_update._swap_unix(
        payload, install, backup_root=backup, provenance_path=staged,
    )

    assert result["ok"] is True
    assert (install / "arena" / "new.py").read_text() == "new"
    assert not (install / "arena" / "old.py").exists()
    assert (backup / "arena" / "old.py").read_text() == "old"
    assert (backup / DEPLOYED_PROVENANCE).read_text() == "old provenance"
    assert (install / DEPLOYED_PROVENANCE).read_text() == "new provenance"
    assert result["rollback_path"] == str(backup)


def test_posix_swap_failure_removes_new_targets_and_restores_old_tree(
    tmp_path: Path, monkeypatch,
) -> None:
    payload = tmp_path / "payload"
    install = tmp_path / "install"
    backup = install / "backups" / "deployments" / "previous"
    (payload / "arena").mkdir(parents=True)
    (payload / "arena" / "new.py").write_text("new")
    (payload / "unified_bridge.py").write_text("new bridge")
    (install / "arena").mkdir(parents=True)
    (install / "arena" / "old.py").write_text("old")
    real_move = auto_update.shutil.move
    calls = 0

    def fail_second(src: str, dst: str) -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("sabotaged second move")
        real_move(src, dst)

    monkeypatch.setattr(auto_update.shutil, "move", fail_second)
    result = auto_update._swap_unix(payload, install, backup_root=backup)

    assert result["ok"] is False
    assert not backup.exists(), "a fully restored failed attempt must remain retryable"
    assert (install / "arena" / "old.py").read_text() == "old"
    assert not (install / "arena" / "new.py").exists()
    assert not (install / "unified_bridge.py").exists()


def test_windows_mover_backs_up_before_copy_and_publishes_provenance_last(tmp_path: Path) -> None:
    payload = tmp_path / "payload"
    install = tmp_path / "install"
    backup = install / "backups" / "deployments" / "4.169.99-old"
    staged = tmp_path / "staging" / DEPLOYED_PROVENANCE
    (payload / "arena").mkdir(parents=True)
    (payload / "arena" / "new.py").write_text("new", encoding="utf-8")
    install.mkdir()
    staged.parent.mkdir()
    staged.write_text("new provenance", encoding="utf-8")

    script = _write_windows_installer(
        payload, install, tmp_path / "done.txt", port=8765,
        backup_root=backup, provenance_path=staged,
    )
    text = script.read_text(encoding="utf-8")
    src = str(payload).replace("/", "\\") + "\\arena"
    dst = str(install).replace("/", "\\") + "\\arena"
    old = str(backup).replace("/", "\\") + "\\arena"
    backup_command = f'robocopy "{dst}" "{old}" /MIR'
    install_command = f'robocopy "{src}" "{dst}" /MIR'
    staged_win = str(staged).replace("/", "\\")
    install_win = str(install).replace("/", "\\")
    provenance_command = (
        f'copy /Y "{staged_win}" "{install_win}\\{DEPLOYED_PROVENANCE}" >NUL'
    )

    assert 'if not errorlevel 1 goto :rollback_dir_ready' in text
    assert 'if errorlevel 1 echo' not in text
    assert backup_command in text
    assert install_command in text
    assert text.index(backup_command) < text.index(install_command)
    backup_win = str(backup).replace("/", "\\")
    backup_provenance_command = (
        f'copy /Y "{install_win}\\{DEPLOYED_PROVENANCE}" '
        f'"{backup_win}\\{DEPLOYED_PROVENANCE}" >NUL'
    )
    assert backup_provenance_command in text
    assert provenance_command in text
    assert text.index(backup_provenance_command) < text.index(install_command)
    assert text.index(backup_provenance_command) < text.index(provenance_command)
    assert text.index(provenance_command) < text.index('echo done >')
    assert ":copy_failed" in text
    assert "if errorlevel 8 goto :copy_failed" in text
