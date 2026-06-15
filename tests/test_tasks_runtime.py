"""Task queue runtime wrapper extraction tests."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import unified_bridge as ub  # noqa: E402
from arena.tasks.runtime import TaskQueueRuntimeContext, make_task_queue_runtime  # noqa: E402


def _runtime(tmp_path: Path):
    return make_task_queue_runtime(TaskQueueRuntimeContext(
        inbox=tmp_path / "inbox",
        running=tmp_path / "running",
        done=tmp_path / "done",
        failed=tmp_path / "failed",
        default_cwd=str(tmp_path),
        now=lambda: "now",
    ))


def test_task_queue_runtime_factory_outputs(tmp_path):
    runtime = _runtime(tmp_path)
    assert callable(runtime.tasks_list_sync)
    assert callable(runtime.task_submit_sync)
    assert callable(runtime.tasks_clean_sync)


def test_unified_task_queue_runtime_bindings():
    assert ub._tasks_list_sync.__module__ == "arena.tasks.runtime"
    assert ub._task_submit_sync.__module__ == "arena.tasks.runtime"
    assert ub._tasks_clean_sync.__module__ == "arena.tasks.runtime"


def test_task_queue_runtime_submit_list_clean(tmp_path):
    runtime = _runtime(tmp_path)
    submitted = runtime.task_submit_sync({"cmd": "echo ok", "title": "unit"})
    assert submitted["ok"] is True
    listed = runtime.tasks_list_sync("", 10)
    assert listed["count"] == 1
    assert listed["tasks"][0]["title"] == "unit"
    assert runtime.tasks_clean_sync()["ok"] is True
