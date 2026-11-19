"""Private-state and leases preserve the parent inode, not a check-then-use path."""
from __future__ import annotations

import contextlib
import os
import stat
from importlib import import_module

import pytest

from arena import private_state
from arena.private_paths import pinned_directory

lease_module = import_module("arena.inventory.cache_lease")


def test_lease_refuses_symlink_parent_and_never_writes_outside(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    linked = tmp_path / "linked"
    linked.symlink_to(outside, target_is_directory=True)
    with pytest.raises(OSError):
        with lease_module.cache_lease(linked / "lease"):
            pytest.fail("a linked parent was accepted")
    assert not (outside / "lease").exists()


@pytest.mark.skipif(os.name == "nt", reason="POSIX directory-descriptor race contract")
def test_lease_publication_uses_pinned_parent_after_rename(tmp_path, monkeypatch):
    parent = tmp_path / "parent"
    parent.mkdir()
    original = tmp_path / "original"
    outside = tmp_path / "outside"
    outside.mkdir()

    @contextlib.contextmanager
    def swapped(path):
        with pinned_directory(path) as fd:
            parent.rename(original)
            parent.symlink_to(outside, target_is_directory=True)
            yield fd

    monkeypatch.setattr(lease_module, "pinned_directory", swapped)
    with lease_module.cache_lease(parent / "lease") as acquired:
        assert acquired is True
        assert (original / "lease").is_file()
        assert not (outside / "lease").exists()


@pytest.mark.skipif(os.name == "nt", reason="POSIX O_NOFOLLOW contract")
def test_lease_refuses_a_preexisting_link_without_writing_target(tmp_path):
    target = tmp_path / "untouched"
    target.write_bytes(b"")
    lease = tmp_path / "lease"
    lease.symlink_to(target)
    with pytest.raises(OSError):
        with lease_module.cache_lease(lease):
            pytest.fail("a linked lease was accepted")
    assert target.read_bytes() == b""


@pytest.mark.skipif(os.name == "nt", reason="POSIX mode bits; Windows uses deployment ACLs")
def test_search_write_only_private_state_does_not_gain_read_permission(tmp_path):
    directory = tmp_path / "search-write-only"
    directory.mkdir()
    directory.chmod(0o300)
    try:
        private_state.private_directory(directory)
        private_state.write_private_json(directory / "known.json", {"kept": True})
        assert stat.S_IMODE(directory.stat().st_mode) == 0o300
    finally:
        directory.chmod(0o700)


@pytest.mark.skipif(os.name == "nt", reason="POSIX umask mode contract")
def test_lease_missing_parent_components_are_private_under_umask_zero(tmp_path):
    shared = tmp_path / "shared"
    shared.mkdir()
    shared.chmod(0o755)
    path = shared / "first" / "second" / "lease"
    old = os.umask(0)
    try:
        with lease_module.cache_lease(path) as acquired:
            assert acquired is True
    finally:
        os.umask(old)
    assert stat.S_IMODE(shared.stat().st_mode) == 0o755
    assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700
    assert stat.S_IMODE(path.parent.parent.stat().st_mode) == 0o700


@pytest.mark.skipif(os.name == "nt", reason="POSIX descriptor-relative token publication")
def test_token_rotation_refuses_a_parent_swap_without_overwriting_outside(tmp_path, monkeypatch):
    from arena import token_storage

    parent = tmp_path / "parent"
    parent.mkdir()
    original = tmp_path / "original"
    outside = tmp_path / "outside"
    outside.mkdir()
    external = outside / "token.txt"
    external.write_text("outside token unchanged")
    external.chmod(0o644)
    real_create = token_storage._create_staged_file

    def swapped(target, parent_fd):
        result = real_create(target, parent_fd)
        parent.rename(original)
        parent.symlink_to(outside, target_is_directory=True)
        return result

    monkeypatch.setattr(token_storage, "_create_staged_file", swapped)
    with pytest.raises(token_storage.TokenFileVanishedError):
        token_storage.write_owner_token(parent / "token.txt", "new owned token")
    assert external.read_text() == "outside token unchanged"
    assert stat.S_IMODE(external.stat().st_mode) == 0o644
    assert (original / "token.txt").read_text() == "new owned token"
    assert not list(original.glob("*.tmp"))


def test_token_rotation_refuses_symlink_parent(tmp_path):
    from arena.token_storage import write_owner_token

    outside = tmp_path / "outside"
    outside.mkdir()
    linked = tmp_path / "linked"
    linked.symlink_to(outside, target_is_directory=True)
    with pytest.raises(OSError):
        write_owner_token(linked / "token.txt", "not for outside")
    assert not (outside / "token.txt").exists()


@pytest.mark.skipif(os.name == "nt", reason="POSIX pinned JSON publication")
def test_json_publication_cannot_be_redirected_after_staging(tmp_path, monkeypatch):
    parent = tmp_path / "parent"
    parent.mkdir()
    original = tmp_path / "original"
    outside = tmp_path / "outside"
    outside.mkdir()
    real_create = private_state.create_staged_file

    def swapped(target, parent_fd):
        result = real_create(target, parent_fd)
        parent.rename(original)
        parent.symlink_to(outside, target_is_directory=True)
        return result

    monkeypatch.setattr(private_state, "create_staged_file", swapped)
    with pytest.raises(OSError, match="parent changed"):
        private_state.write_private_json(parent / "task.json", {"not": "outside"})
    assert not (outside / "task.json").exists()
    assert (original / "task.json").is_file()


@pytest.mark.skipif(os.name == "nt", reason="POSIX private parent creation")
def test_new_token_parents_are_private_without_chmodding_shared_ancestor(tmp_path):
    from arena.token_storage import write_owner_token

    shared = tmp_path / "shared"
    shared.mkdir()
    shared.chmod(0o755)
    target = shared / "new" / "nested" / "token.txt"
    old = os.umask(0)
    try:
        write_owner_token(target, "owned token")
    finally:
        os.umask(old)
    assert stat.S_IMODE(shared.stat().st_mode) == 0o755
    assert stat.S_IMODE(target.parent.parent.stat().st_mode) == 0o700
    assert stat.S_IMODE(target.parent.stat().st_mode) == 0o700
    assert stat.S_IMODE(target.stat().st_mode) == 0o600
