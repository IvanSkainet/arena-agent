"""A stopped streaming consumer must not deadlock bounded output cleanup."""
from __future__ import annotations

import asyncio
import os
import shlex
import subprocess
import sys

import psutil

from arena.exec import runner


def test_close_reaps_stream_with_full_output_queue(tmp_path, monkeypatch):
    async def scenario():
        queues = []
        original = runner._pump_stream_output

        async def observed_pump(stream, tag, queue):
            queues.append(queue)
            await original(stream, tag, queue)

        async def wait_for_full_queue():
            while not any(queue.full() for queue in queues):
                await asyncio.sleep(0.01)

        monkeypatch.setattr(runner, "_pump_stream_output", observed_pump)
        marker = tmp_path / "pid.txt"
        script = tmp_path / "flood.py"
        script.write_text(
            "import os,sys,time\nfrom pathlib import Path\n"
            f"Path({str(marker)!r}).write_text(str(os.getpid()))\n"
            "sys.stdout.buffer.write(b'x'*2000000)\nsys.stdout.flush()\ntime.sleep(60)\n"
        )
        argv = [sys.executable, str(script)]
        command = subprocess.list2cmdline(argv) if os.name == "nt" else shlex.join(argv)
        stream = runner.run_shell_command_stream(
            request_id="backpressure-close-490", cmd=command, cwd=tmp_path,
            env=os.environ.copy(), timeout=60, max_output=3000000,
        )
        try:
            event = await anext(stream)
            assert event["type"] == "start"
            output = await anext(stream)
            assert output["type"] == "stdout"
            await asyncio.wait_for(wait_for_full_queue(), timeout=15)
            await asyncio.wait_for(stream.aclose(), timeout=15)
            owned_pids = (event["pid"], int(marker.read_text()))

            async def wait_for_reaping():
                while any(psutil.pid_exists(pid) for pid in owned_pids):
                    await asyncio.sleep(0.01)

            await asyncio.wait_for(wait_for_reaping(), timeout=15)
            assert "backpressure-close-490" not in runner.ACTIVE_PROCESSES
        finally:
            await stream.aclose()

    asyncio.run(scenario())
