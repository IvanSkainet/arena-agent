"""Task queue runtime helper tests."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from arena.tasks.queue import clean_tasks, list_tasks, submit_task  # noqa: E402
import unified_bridge as ub  # noqa: E402


def test_submit_and_list_tasks(tmp_path):
    inbox = tmp_path / "inbox"; running = tmp_path / "running"; done = tmp_path / "done"; failed = tmp_path / "failed"
    for d in [inbox, running, done, failed]:
        d.mkdir(parents=True)
    submitted = submit_task({"cmd": "echo hi", "title": "hello"}, inbox=inbox, default_cwd=str(tmp_path), now_fn=lambda: "now")
    assert submitted["ok"] is True
    listed = list_tasks(inbox=inbox, running=running, done=done, failed=failed, limit=10)
    assert listed["count"] == 1
    assert listed["tasks"][0]["cmd"] == "echo hi"
    assert "stdout" not in listed["tasks"][0]


def test_clean_tasks_removes_old_done_failed(tmp_path):
    done = tmp_path / "done"; failed = tmp_path / "failed"
    done.mkdir(); failed.mkdir()
    (done / "a.json").write_text(json.dumps({"id": "a"}), encoding="utf-8")
    (failed / "b.json").write_text(json.dumps({"id": "b"}), encoding="utf-8")
    res = clean_tasks(done=done, failed=failed, older_than_seconds=-1)
    assert res["removed"] == 2


def test_unified_bridge_tasks_wrappers():
    assert ub._tasks_list_sync("", 1)["ok"] is True
