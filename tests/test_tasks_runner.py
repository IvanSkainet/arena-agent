"""Background task runner extraction tests."""
import asyncio
import json
import sys
import shlex
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import unified_bridge as ub  # noqa: E402
from arena.tasks.runner import TaskRunnerContext, make_task_runner_runtime, move_atomic  # noqa: E402


def _ctx(tmp_path: Path, blocked_reason=lambda cmd: None, cleaned=None):
    cleaned = cleaned if cleaned is not None else []
    return TaskRunnerContext(
        inbox=tmp_path / "inbox",
        running=tmp_path / "running",
        done=tmp_path / "done",
        failed=tmp_path / "failed",
        blocked_reason=blocked_reason,
        cleanup_mcp_sessions=lambda: cleaned.pop(0) if cleaned else 0,
        utc_now=lambda: "now",
        log_info=lambda *args, **kwargs: None,
        log_error=lambda *args, **kwargs: None,
    )


def test_task_runner_factory_outputs(tmp_path):
    runtime = make_task_runner_runtime(_ctx(tmp_path))
    assert callable(runtime.move_atomic)
    assert callable(runtime.ensure_dirs)
    assert callable(runtime.run_one)
    assert callable(runtime.runner_loop)


def test_unified_task_runner_bound_to_runner_module():
    assert ub.move_atomic.__module__ == "arena.tasks.runner"
    assert ub.task_ensure_dirs.__module__ == "arena.tasks.runner"
    assert ub.task_run_one.__module__ == "arena.tasks.runner"
    assert ub.task_runner_loop.__module__ == "arena.tasks.runner"


def test_move_atomic_fallback_or_rename(tmp_path):
    src = tmp_path / "src.txt"
    dst = tmp_path / "dst.txt"
    src.write_text("hello", encoding="utf-8")
    move_atomic(src, dst)
    assert not src.exists()
    assert dst.read_text(encoding="utf-8") == "hello"


def test_task_runner_run_one_success(tmp_path):
    runtime = make_task_runner_runtime(_ctx(tmp_path))
    runtime.ensure_dirs()
    task_path = tmp_path / "inbox" / "t1.json"
    py_cmd = f'"{sys.executable}" -c "print(123)"' if sys.platform == "win32" else f"{shlex.quote(sys.executable)} -c 'print(123)'"
    task_path.write_text(json.dumps({
        "id": "t1",
        "cmd": py_cmd,
        "cwd": str(tmp_path),
        "timeout": 10,
    }), encoding="utf-8")

    assert asyncio.run(runtime.run_one(task_path)) is True
    done = tmp_path / "done" / "t1.json"
    assert done.exists()
    data = json.loads(done.read_text(encoding="utf-8"))
    assert data["state"] == "done"
    assert data["exit_code"] == 0
    assert "123" in data["stdout"]


def test_task_runner_run_one_blocked(tmp_path):
    runtime = make_task_runner_runtime(_ctx(tmp_path, blocked_reason=lambda cmd: "blocked-test"))
    runtime.ensure_dirs()
    task_path = tmp_path / "inbox" / "t2.json"
    task_path.write_text(json.dumps({"id": "t2", "cmd": "echo nope", "cwd": str(tmp_path)}), encoding="utf-8")

    asyncio.run(runtime.run_one(task_path))
    failed = tmp_path / "failed" / "t2.json"
    assert failed.exists()
    data = json.loads(failed.read_text(encoding="utf-8"))
    assert data["state"] == "failed"
    assert data["exit_code"] == -1
    assert "blocked-test" in data["stderr"]
