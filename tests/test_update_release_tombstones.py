"""T56: removed release files must not survive successful archive updates."""
from __future__ import annotations

from pathlib import Path

import pytest

from arena.admin.deployment_tombstones import (
    REMOVED_RELEASE_TARGETS,
    stage_release_tombstones,
)


def test_legacy_version_marker_is_staged_for_ephemeral_rollback(tmp_path: Path) -> None:
    assert REMOVED_RELEASE_TARGETS == ("version.json",)
    marker = tmp_path / "version.json"
    marker.write_text('{"version":"4.153.3"}', encoding="utf-8")

    pairs = stage_release_tombstones(tmp_path, backup_root=None, timestamp=123)

    backup = tmp_path / ".version.json.old-123"
    assert pairs == [(backup, marker)]
    assert not marker.exists()
    assert backup.read_text(encoding="utf-8") == '{"version":"4.153.3"}'
    backup.rename(marker)
    assert marker.is_file(), "the ordinary swap rollback can restore the tombstone"


def test_identified_rollback_tree_retains_removed_file(tmp_path: Path) -> None:
    marker = tmp_path / "version.json"
    marker.write_text("legacy", encoding="utf-8")
    rollback = tmp_path / "backups" / "deployments" / "old-id"
    rollback.mkdir(parents=True)

    pairs = stage_release_tombstones(tmp_path, backup_root=rollback, timestamp=123)

    assert pairs == [(rollback / "version.json", marker)]
    assert (rollback / "version.json").read_text() == "legacy"
    assert not marker.exists()


def test_absent_tombstone_is_a_noop(tmp_path: Path) -> None:
    assert stage_release_tombstones(tmp_path, backup_root=None, timestamp=123) == []


def test_dangling_symlink_tombstone_is_staged_without_following_target(tmp_path: Path) -> None:
    marker = tmp_path / "version.json"
    try:
        marker.symlink_to(tmp_path / "missing-target")
    except (OSError, NotImplementedError):
        pytest.skip("symlinks unavailable")

    pairs = stage_release_tombstones(tmp_path, backup_root=None, timestamp=123)

    backup = tmp_path / ".version.json.old-123"
    assert pairs == [(backup, marker)]
    assert backup.is_symlink()
    assert not marker.is_symlink()


def test_tombstone_refuses_directory_shaped_surprise(tmp_path: Path) -> None:
    marker = tmp_path / "version.json"
    marker.mkdir()
    with pytest.raises(IsADirectoryError) as caught:
        stage_release_tombstones(tmp_path, backup_root=None, timestamp=123)
    assert str(caught.value) == f"release tombstone is a directory: {marker}"
    assert marker.is_dir()
