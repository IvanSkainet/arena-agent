"""Adversarial review cases for pinned journals and in-flight child creation."""
from __future__ import annotations

import asyncio
import contextlib
import json
import os
import stat
from pathlib import Path
from types import SimpleNamespace

import pytest

from arena import file_lock, private_paths
from arena.agent_helpers import journal


def test_reparse_tags_are_rejected_without_path_is_junction(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "lstat", lambda self: SimpleNamespace(
        st_mode=stat.S_IFDIR, st_reparse_tag=0xA0000003))
    assert private_paths.is_linked_path(tmp_path)


@pytest.mark.skipif(os.name == "nt", reason="POSIX descriptor-relative rename contract")
def test_journal_and_lock_keep_the_same_parent_after_rename(tmp_path, monkeypatch):
    parent = tmp_path / "parent"
    parent.mkdir()
    original = tmp_path / "original"
    outside = tmp_path / "outside"
    outside.mkdir()
    external = outside / "facts.jsonl"
    external.write_text("outside unchanged")
    real_lease = file_lock.lease_in_directory

    @contextlib.contextmanager
    def renamed(path, parent_fd):
        with real_lease(path, parent_fd) as held:
            parent.rename(original)
            parent.symlink_to(outside, target_is_directory=True)
            yield held

    monkeypatch.setattr(file_lock, "lease_in_directory", renamed)
    journal.append_fact_record(parent / "facts.jsonl", {"key": "owned"})
    assert external.read_text() == "outside unchanged"
    assert json.loads((original / "facts.jsonl").read_text()) == {"key": "owned"}
    assert not (outside / "facts.jsonl.append-lock").exists()


def test_journal_refuses_link_when_directory_descriptors_are_unavailable(tmp_path, monkeypatch):
    external = tmp_path / "outside"
    external.write_text("unchanged")
    linked = tmp_path / "facts.jsonl"
    linked.symlink_to(external)

    @contextlib.contextmanager
    def no_descriptor(*args):
        yield None

    monkeypatch.setattr(journal, "journal_lock", no_descriptor)
    with pytest.raises(OSError, match="linked fact journal"):
        journal.append_fact_record(linked, {"key": "must not write"})
    assert external.read_text() == "unchanged"


@pytest.mark.skipif(os.name == "nt", reason="POSIX FIFO contract")
def test_queue_fifo_is_rejected_without_a_reader_or_mode_change(tmp_path):
    from arena.mcp.ws_push import _prepare_notify_queue

    queue = tmp_path / "queue"
    os.mkfifo(queue, 0o600)
    with pytest.raises(OSError):
        _prepare_notify_queue(queue)
    assert stat.S_ISFIFO(queue.lstat().st_mode)
    assert stat.S_IMODE(queue.lstat().st_mode) == 0o600


def test_desktop_cancellation_reaps_a_child_whose_spawn_has_not_returned(monkeypatch):
    from arena.desktop import exec as desktop

    async def exercise():
        started, release = asyncio.Event(), asyncio.Event()
        calls = []

        class Process:
            async def wait(self):
                calls.append("waited")
                return -9

        process = Process()

        async def spawn(*args, **kwargs):
            started.set()
            await release.wait()
            return process

        monkeypatch.setattr(asyncio, "create_subprocess_shell", spawn)
        monkeypatch.setattr(desktop, "_kill_process_tree", lambda proc: calls.append("killed"))
        task = asyncio.create_task(desktop._desktop_exec("fixture"))
        await started.wait()
        task.cancel()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert calls == ["killed", "waited"]

    asyncio.run(exercise())


def test_deeply_nested_task_is_rejected_without_escaping_the_reader(tmp_path):
    from arena.tasks.runner import TaskRunnerContext, _read_submission

    submission = tmp_path / "deep.json"
    submission.write_text("[" * 10000 + "0" + "]" * 10000)
    errors = []
    context = TaskRunnerContext(
        inbox=tmp_path, running=tmp_path, done=tmp_path, failed=tmp_path,
        blocked_reason=lambda command: None, cleanup_mcp_sessions=lambda: 0,
        utc_now=lambda: "now", log_info=lambda *args: None,
        log_error=lambda *args: errors.append(args))
    assert _read_submission(submission, context) is None
    assert len(errors) == 1


def test_recovery_tolerates_a_staging_leaf_already_removed(tmp_path, monkeypatch):
    from arena.tasks import queue

    real_link = queue._link_failed_task

    def published_and_cleaned(staged, target, parent_fd):
        installed = real_link(staged, target, parent_fd)
        private_paths.unlink_staged(staged, parent_fd)
        return installed

    monkeypatch.setattr(queue, "_link_failed_task", published_and_cleaned)
    target = tmp_path / "failed.json"
    assert queue._publish_failed_task(target, {"id": "owned"}) is True
    assert json.loads(target.read_text()) == {"id": "owned"}
