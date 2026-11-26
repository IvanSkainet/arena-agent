"""The GitHub token saved from the dashboard is staged like the bearer token (#611)."""
from __future__ import annotations

import json
import os
import stat
from pathlib import Path

import pytest

from arena import token_storage
from arena.admin import update_github

TOKEN = "ghp_" + "k" * 40
OLDER = "ghp_" + "o" * 40
STAGING = ".github_token.tmp"


@pytest.fixture(name="target")
def _target(monkeypatch, tmp_path):
    """An install root of the test's own; the token file is not there yet."""
    root = tmp_path / "install-root"
    root.mkdir()
    path = root / ".github_token"
    monkeypatch.setattr(update_github, "_token_file_path", lambda: path)
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("GH_TOKEN", raising=False)
    return path


def _names(directory: Path) -> list[str]:
    """What is in the install root, by name."""
    return sorted(entry.name for entry in directory.iterdir())


def test_a_saved_token_is_read_back_and_nothing_else_is_left(target):
    """One file in the install root, and it holds the token."""
    result = update_github.save_github_token(TOKEN)
    assert result == {"ok": True, "path": str(target), "source": "file"}
    assert update_github.github_token() == TOKEN
    assert _names(target.parent) == [".github_token"]


@pytest.mark.skipif(os.name != "posix", reason="mode bits are not the protection on Windows")
def test_the_staged_file_is_owner_only_from_the_moment_it_exists(target, monkeypatch):
    """The mode is read from the descriptor at the point the staged file is created."""
    created = []
    real = token_storage._create_staged_file

    def recording(path, parent_fd):
        descriptor, name = real(path, parent_fd)
        created.append((name.name, stat.S_IMODE(os.fstat(descriptor).st_mode)))
        return descriptor, name

    monkeypatch.setattr(token_storage, "_create_staged_file", recording)
    result = update_github.save_github_token(TOKEN)
    assert result["ok"] is True
    assert [mode for _, mode in created] == [0o600]
    assert created[0][0] != STAGING
    assert stat.S_IMODE(target.stat().st_mode) == 0o600


def test_a_write_that_fails_leaves_no_copy_of_the_new_token(target, monkeypatch):
    """The earlier token stays, and no staging file holds the new one."""
    assert update_github.save_github_token(OLDER)["ok"] is True

    def refuse(_staged, _target):
        raise PermissionError(13, "the file is in use")

    monkeypatch.setattr(token_storage, "_replace_and_settle", refuse)
    result = update_github.save_github_token(TOKEN)
    assert result["ok"] is False
    assert "PermissionError" in result["error"]
    assert TOKEN not in json.dumps(result)
    assert update_github.github_token() == OLDER
    assert _names(target.parent) == [".github_token"]


def test_a_mode_that_could_not_be_reapplied_is_a_saved_token_with_a_warning(target, monkeypatch):
    """The file already holds the token, so reporting a failure would be wrong."""
    real = update_github.write_owner_token

    def written_then_warned(path, text):
        real(path, text)
        raise token_storage.TokenFileModeWarning(path, OSError("chmod refused"))

    monkeypatch.setattr(update_github, "write_owner_token", written_then_warned)
    result = update_github.save_github_token(TOKEN)
    assert result["ok"] is True
    assert str(target) in result["warning"]
    assert TOKEN not in json.dumps(result)
    assert update_github.github_token() == TOKEN


def test_a_symlink_where_the_token_file_goes_is_refused(target, tmp_path):
    """The writer does not follow it and does not replace it."""
    elsewhere = tmp_path / "elsewhere"
    elsewhere.write_text("untouched", encoding="utf-8")
    try:
        target.symlink_to(elsewhere)
    except OSError:
        pytest.skip("this account may not create symlinks")
    result = update_github.save_github_token(TOKEN)
    assert result["ok"] is False
    assert elsewhere.read_text(encoding="utf-8") == "untouched"
    assert target.is_symlink()


def test_saving_removes_the_staging_file_an_earlier_version_left(target):
    """Up to 4.171.0 a failed replace left the token in `.github_token.tmp`."""
    (target.parent / STAGING).write_text(OLDER, encoding="utf-8")
    result = update_github.save_github_token(TOKEN)
    assert result == {"ok": True, "path": str(target), "source": "file"}
    assert _names(target.parent) == [".github_token"]


def test_a_staging_file_that_cannot_be_removed_is_reported_and_the_token_is_saved(target):
    """The save took effect; the operator is told a copy may remain."""
    stuck = target.parent / STAGING
    (stuck / "inside").mkdir(parents=True)
    result = update_github.save_github_token(TOKEN)
    assert result["ok"] is True
    assert str(stuck) in result["warning"]
    assert TOKEN not in json.dumps(result)
    assert update_github.github_token() == TOKEN


@pytest.mark.parametrize("saved", [True, False])
def test_clearing_removes_that_staging_file_too(target, saved):
    """After "clear" no copy of a token is left, whether or not one was saved."""
    if saved:
        assert update_github.save_github_token(TOKEN)["ok"] is True
    (target.parent / STAGING).write_text(OLDER, encoding="utf-8")
    result = update_github.clear_github_token()
    assert result == {"ok": True, "removed": saved, "path": str(target)}
    assert _names(target.parent) == []


def test_clearing_says_so_when_the_staging_file_cannot_be_removed(target):
    """A copy that may still be there is not reported as cleared."""
    stuck = target.parent / STAGING
    (stuck / "inside").mkdir(parents=True)
    assert update_github.save_github_token(TOKEN)["ok"] is True
    result = update_github.clear_github_token()
    assert result["ok"] is False
    assert result["removed"] is True
    assert str(stuck) in result["error"]
    assert update_github.github_token() is None
