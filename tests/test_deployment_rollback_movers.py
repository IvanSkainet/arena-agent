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
    assert result["restored"] is True
    assert result["rollback_path"] == str(backup)
    assert result["rollback_retained"] is False
    assert not backup.exists(), "a fully restored failed attempt must remain retryable"
    assert (install / "arena" / "old.py").read_text() == "old"
    assert not (install / "arena" / "new.py").exists()
    assert not (install / "unified_bridge.py").exists()


def test_posix_failed_restore_reports_retained_snapshot(tmp_path: Path, monkeypatch) -> None:
    payload = tmp_path / "payload"
    install = tmp_path / "install"
    backup = install / "backups" / "deployments" / "previous"
    (payload / "arena").mkdir(parents=True)
    (payload / "arena" / "new.py").write_text("new")
    (payload / "unified_bridge.py").write_text("new bridge")
    (install / "arena").mkdir(parents=True)
    (install / "arena" / "old.py").write_text("old")
    real_move = auto_update.shutil.move
    real_rename = Path.rename
    move_calls = 0
    rename_calls = 0

    def fail_second_move(src: str, dst: str) -> None:
        nonlocal move_calls
        move_calls += 1
        if move_calls == 2:
            raise OSError("sabotaged move")
        real_move(src, dst)

    def fail_restore(self: Path, target: Path):
        nonlocal rename_calls
        rename_calls += 1
        if rename_calls == 2:
            raise OSError("sabotaged restore")
        return real_rename(self, target)

    monkeypatch.setattr(auto_update.shutil, "move", fail_second_move)
    monkeypatch.setattr(Path, "rename", fail_restore)
    result = auto_update._swap_unix(payload, install, backup_root=backup)

    assert result["ok"] is False
    assert result["restored"] is False
    assert result["rollback_retained"] is True
    assert result["rollback_path"] == str(backup)
    assert (backup / "arena" / "old.py").read_text() == "old"


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
    assert 'set _install_started=1' in text
    assert 'set _backup_created=0' in text
    assert ':rollback_dir_ready\nset _backup_created=1' in text
    assert 'if not "%_backup_created%"=="1" goto :rollback_backup_preserved' in text
    assert ':rollback_backup_preserved\nset _update_failed=1\ngoto :launch_recovery' in text
    assert '.arena-target-0-dir' in text
    assert ':rollback_dir_0' in text
    assert f'robocopy "{old}" "{dst}" /MIR' in text
    assert text.index(':copy_failed') < text.index(':rollback_dir_0')
    assert 'ERROR rollback incomplete; retained snapshot=' in text
    assert ':launch_recovery' in text
    assert 'if "%_update_failed%"=="1" goto :recovery_exit' in text
    assert text.index(':rollback_provenance_done') < text.rindex(f'rmdir "{install_win}\\.arena-update-apply.lock"')
