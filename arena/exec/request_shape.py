"""What an exec request asked for, once the body has been checked.

Two readers, split out of `handlers.py` because that module crossed the
600-line ceiling in `test_architecture_boundaries.py` when #270 added the
validation, and because both are pure functions of the body: no request, no
response, no context beyond the numbers on it.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from arena.exec.environment import filter_caller_env
from arena.handler_params import body_int, body_str

__all__ = ["limits_and_env", "requested_cwd"]


def requested_cwd(data: dict[str, Any], root: Path) -> tuple[Path | None, str]:
    """The working directory this request asked for, or why it cannot be one.

    `body_str` refuses a `cwd` that is not a string -- that raises past this
    function and becomes the usual field-named 400. A string, though, can
    still be a path the filesystem refuses to answer questions about:
    `~nobody` has no home to expand into (RuntimeError) and a 300-character
    component is `OSError: File name too long` rather than False. Both were
    500s, both are the caller's to fix, so both are a 400 (#270).
    """
    raw = body_str(data, "cwd", default="") or str(root)
    try:
        cwd = Path(raw).expanduser()
        cwd = cwd if cwd.is_absolute() else root / cwd
        if not cwd.exists() or not cwd.is_dir():
            return None, f"cwd does not exist: {cwd}"
    except (OSError, RuntimeError, ValueError) as exc:
        return None, f"cwd is not a usable path ({type(exc).__name__})"
    return cwd, ""


def limits_and_env(data: dict[str, Any], cfg: Any, ctx: Any) -> tuple[int, int, dict[str, str]]:
    """The three request-scoped limits both exec handlers read the same way.

    Written once because it was written twice: SonarCloud counts the copies
    as duplicated lines, and #270 had to fix the same `int(data.get(...))`
    in both. `timeout` and `max_output` are clamped to the profile's
    ceilings -- a body cannot raise them, only lower them.
    """
    # `or` after the parse, deliberately: the idiom this replaced was
    # `int(data.get("timeout") or cfg["timeout"])`, where 0 fell through to
    # the default. `body_int` treats 0 as a real value, so without this a
    # client sending `{"timeout": 0}` -- which works today -- would get
    # `asyncio.wait_for(timeout=0)` and an immediate 408. A bug fix must not
    # break a request that currently succeeds (cubic caught this).
    timeout = min(
        body_int(data, "timeout", default=0) or int(cfg["timeout"]),
        cfg["max_timeout"])
    max_output = min(
        body_int(data, "max_output", default=0) or int(ctx.default_max_output),
        cfg["max_output"])
    raw_env = data.get("env")
    env_extra: dict[str, Any] = dict(raw_env) if isinstance(raw_env, dict) else {}
    env = os.environ.copy()
    env.update(filter_caller_env(env_extra))
    return timeout, max_output, env
