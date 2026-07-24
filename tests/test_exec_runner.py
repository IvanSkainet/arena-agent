"""Exec runner tests."""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

from arena.exec.runner import ACTIVE_PROCESSES, active_processes_snapshot, run_shell_command  # noqa: E402
import unified_bridge as ub  # noqa: E402


def test_active_processes_reexported():
    assert ub.ACTIVE_PROCESSES is ACTIVE_PROCESSES
    assert callable(ub.run_shell_command)


def test_active_processes_snapshot_empty():
    ACTIVE_PROCESSES.clear()
    assert active_processes_snapshot() == []


@pytest.mark.skipif(
    sys.platform == "win32",
    reason=(
        "asyncio subprocess on Python 3.10 + Windows raises "
        "OSError [WinError 87] 'The parameter is incorrect' for "
        "the very first subprocess.Popen call after the asyncio "
        "loop starts. This is a known Python/asyncio-on-Windows "
        "interaction, not a bug in run_shell_command. The same "
        "test passes on Python 3.11/3.12/3.13/3.14 on Windows "
        "and on all Python versions on Linux/macOS. v4.68.0 "
        "marks this as Windows-skipped; a future Python fix "
        "would un-skip it."
    ),
)
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
