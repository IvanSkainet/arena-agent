"""Exec runner tests."""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from arena.exec.runner import ACTIVE_PROCESSES, active_processes_snapshot, run_shell_command  # noqa: E402
import unified_bridge as ub  # noqa: E402


def test_active_processes_reexported():
    assert ub.ACTIVE_PROCESSES is ACTIVE_PROCESSES
    assert callable(ub.run_shell_command)


def test_active_processes_snapshot_empty():
    ACTIVE_PROCESSES.clear()
    assert active_processes_snapshot() == []


def test_run_shell_command_success(tmp_path):
    async def run():
        return await run_shell_command(
            request_id="test",
            cmd="echo hello",
            cwd=tmp_path,
            env={},
            timeout=10,
            max_output=1000,
            decode_output_fn=lambda b: b.decode("utf-8", "replace"),
        )
    res = asyncio.run(run())
    assert res["ok"] is True
    assert res["exit_code"] == 0
    assert "hello" in res["stdout"]
    assert "test" not in ACTIVE_PROCESSES
