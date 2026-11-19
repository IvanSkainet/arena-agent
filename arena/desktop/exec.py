"""Desktop command execution helper."""
from __future__ import annotations

import asyncio

from arena.exec.runner import _kill_process_tree, _process_group_kwargs


async def _desktop_exec(cmd: str, timeout: float = 10) -> dict:
    """Run a desktop automation command and return result dict.

    v4.169.6: the timeout handler called `proc.kill()` on a name that
    may never have been bound. `create_subprocess_shell` can raise --
    OSError when the shell is missing, PermissionError under a
    restricted profile, NotImplementedError on some Windows event loop
    policies -- and the `except asyncio.TimeoutError` branch would then
    fire on a later timeout with `proc` undefined, turning a clean error
    message into a `NameError` from inside an exception handler.

    Found by Pyright (`reportPossiblyUnboundVariable`), which had been
    saying so on every run. Nobody was reading Pyright.

    Two changes: `proc` is bound before the try, and the timeout branch
    now also *reaps* the killed process. Without the `await`, killing it
    leaves a zombie and asyncio logs "Task was destroyed but it is
    pending" -- a kill that does not wait is only half a cleanup.
    """
    proc: asyncio.subprocess.Process | None = None
    spawn: asyncio.Future[asyncio.subprocess.Process] | None = None
    try:
        spawn = asyncio.ensure_future(asyncio.create_subprocess_shell(
            cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            **_process_group_kwargs(),
        ))
        proc = await asyncio.shield(spawn)
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        return {
            "ok": proc.returncode == 0,
            "exit_code": proc.returncode,
            "stdout": stdout.decode("utf-8", errors="replace"),
            "stderr": stderr.decode("utf-8", errors="replace"),
        }
    except asyncio.TimeoutError:
        if proc is not None:
            try:
                await asyncio.to_thread(_kill_process_tree, proc)
                # Reap it. A killed child that is never awaited stays a
                # zombie and asyncio complains about a pending task.
                await proc.wait()
            except ProcessLookupError:
                pass  # already gone between the timeout and the kill
        return {"ok": False, "error": f"Command timed out ({timeout}s)"}
    except asyncio.CancelledError:
        if spawn is not None:
            await _reap_cancelled_spawn(spawn, proc)
        raise
    except Exception as e:
        return {"ok": False, "error": str(e)}


async def _reap_cancelled_spawn(spawn: asyncio.Future[asyncio.subprocess.Process],
                                proc: asyncio.subprocess.Process | None) -> None:
    """A cancelled caller still owns the child whose spawn is in flight."""
    if proc is None:
        try:
            proc = await spawn
        except (OSError, ValueError, RuntimeError):
            return  # Spawn failed without returning a child to own.
    await asyncio.to_thread(_kill_process_tree, proc)
    await proc.wait()
