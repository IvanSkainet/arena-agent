"""Queue initialization cannot chmod an unrelated symlink target."""
import os
import stat

import pytest

from arena.mcp.ws_push import _prepare_notify_queue


@pytest.mark.skipif(os.name == "nt", reason="POSIX O_NOFOLLOW and mode contract")
def test_queue_symlink_does_not_change_target_permissions(tmp_path):
    outside = tmp_path / "outside"
    outside.write_text("untouched")
    outside.chmod(0o644)
    queue = tmp_path / "private" / "queue"
    queue.parent.mkdir()
    queue.symlink_to(outside)
    with pytest.raises(OSError):
        _prepare_notify_queue(queue)
    assert stat.S_IMODE(outside.stat().st_mode) == 0o644
    assert outside.read_text() == "untouched"


@pytest.mark.skipif(os.name == "nt", reason="Windows privacy uses owner deployment ACLs")
def test_existing_notify_queue_is_private_without_losing_data(tmp_path):
    queue = tmp_path / "queue"
    queue.write_text("keep queued event\n")
    queue.chmod(0o666)
    _prepare_notify_queue(queue)
    assert stat.S_IMODE(queue.stat().st_mode) == 0o600
    assert queue.read_text() == "keep queued event\n"
