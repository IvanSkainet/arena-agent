"""A streaming command that is closed early must not leave its pipes open (#593)."""
from __future__ import annotations

import asyncio
import gc
import os
import sys
import warnings

import pytest

from arena.exec import runner


async def _close_a_stream_whose_output_is_backed_up(tmp_path, monkeypatch):
    queues = []
    original = runner._pump_stream_output

    async def observed_pump(stream, tag, queue):
        queues.append(queue)
        await original(stream, tag, queue)

    async def wait_for_full_queue():
        while not any(queue.full() for queue in queues):
            await asyncio.sleep(0.01)

    monkeypatch.setattr(runner, "_pump_stream_output", observed_pump)
    script = tmp_path / "flood.py"
    script.write_text(
        "import sys,time\n"
        "sys.stdout.buffer.write(b'x'*2000000)\nsys.stdout.flush()\ntime.sleep(60)\n"
    )
    # The script is named relative to cwd, so only the interpreter needs quotes;
    # one quoted word followed by a plain one reads the same in cmd.exe and sh.
    stream = runner.run_shell_command_stream(
        request_id="closes-its-pipes-593", cmd=f'"{sys.executable}" {script.name}', cwd=tmp_path,
        env=os.environ.copy(), timeout=60, max_output=3000000,
    )
    try:
        assert (await anext(stream))["type"] == "start"
        assert (await anext(stream))["type"] == "stdout"
        await asyncio.wait_for(wait_for_full_queue(), timeout=15)
    finally:
        await asyncio.wait_for(stream.aclose(), timeout=15)


def test_closing_a_backed_up_stream_leaves_no_open_transport(tmp_path, monkeypatch):
    """Nothing is left for the garbage collector to complain about."""
    unraisable = []
    monkeypatch.setattr(sys, "unraisablehook", unraisable.append)
    gc.collect()
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always", ResourceWarning)
        asyncio.run(_close_a_stream_whose_output_is_backed_up(tmp_path, monkeypatch))
        gc.collect()
    # POSIX: the destructor of an unclosed transport emits a ResourceWarning.
    unclosed = [str(w.message) for w in caught if "unclosed transport" in str(w.message)]
    # Windows: the destructor itself fails, which reaches the unraisable hook.
    failed = [repr(u.object) for u in unraisable if "Transport" in repr(u.object)]
    if unclosed or failed:
        pytest.fail(f"the stream left a transport open: {unclosed + failed}")
