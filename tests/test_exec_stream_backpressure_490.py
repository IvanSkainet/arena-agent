"""A stopped streaming consumer must not deadlock bounded output cleanup."""
from __future__ import annotations

import asyncio
import os
import shlex
import subprocess
import sys

from arena.exec import runner


def test_close_reaps_stream_with_full_output_queue(tmp_path, monkeypatch):
    async def scenario():
        full = asyncio.Event()
        original = asyncio.Queue

        class ObservedQueue(original):
            async def put(self, item):
                if self.full():
                    full.set()
                await super().put(item)

        monkeypatch.setattr(runner.asyncio, "Queue", ObservedQueue)
        script = tmp_path / "flood.py"
        script.write_text("import sys,time\nsys.stdout.buffer.write(b'x'*2000000)\nsys.stdout.flush()\ntime.sleep(60)\n")
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
            await asyncio.wait_for(full.wait(), timeout=15)
            await asyncio.wait_for(stream.aclose(), timeout=15)
            assert "backpressure-close-490" not in runner.ACTIVE_PROCESSES
        finally:
            await stream.aclose()

    asyncio.run(scenario())
