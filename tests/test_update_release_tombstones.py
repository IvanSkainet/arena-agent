"""T56: removed release files must not survive copy-only updates."""
from __future__ import annotations

from pathlib import Path

import pytest

from arena.admin.deployment_tombstones import (
    REMOVED_RELEASE_TARGETS,
    remove_release_tombstones,
)


def test_legacy_version_marker_is_the_only_release_tombstone(tmp_path: Path) -> None:
    assert REMOVED_RELEASE_TARGETS == ("version.json",)
    marker = tmp_path / "version.json"
    marker.write_text('{"version":"4.153.3"}', encoding="utf-8")
    assert remove_release_tombstones(tmp_path) == ("version.json",)
    assert not marker.exists()
    assert remove_release_tombstones(tmp_path) == ()


def test_tombstone_refuses_directory_shaped_surprise(tmp_path: Path) -> None:
    marker = tmp_path / "version.json"
    marker.mkdir()
    with pytest.raises(IsADirectoryError) as caught:
        remove_release_tombstones(tmp_path)
    assert str(caught.value) == f"release tombstone is a directory: {marker}"
    assert marker.is_dir()
