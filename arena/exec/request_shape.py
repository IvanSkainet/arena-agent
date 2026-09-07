"""What an exec request asked for, once the body has been checked.

Two readers, split out of `handlers.py` because that module crossed the
600-line ceiling in `test_architecture_boundaries.py` when #270 added the
validation, and because both are pure functions of the body: no request, no
response, no context beyond the numbers on it.
"""
from __future__ import annotations

import os
from collections.abc import Callable
from pathlib import Path
from typing import Any

from arena.exec.environment import filter_caller_env
from arena.handler_errors import BodyFieldError
from arena.handler_params import body_int, body_str

__all__ = ["OUTSIDE_ROOT", "limits_and_env", "requested_cwd", "usable_cwd"]

# Said three times otherwise, which SonarCloud counts (S1192) and which is
# also how two of the three drifted apart in the first place.
OUTSIDE_ROOT = "cwd must be under root"


def usable_cwd(raw: str, root: Path,
               *, under_root: Callable[[Path, Path], bool] | None = None,
               ) -> tuple[Path | None, str]:
    """A directory the request named, or why it cannot be one.

    A string can be a path the filesystem refuses to answer questions
    about: `~nobody` has no home to expand into (RuntimeError), `~Qm` the
    same, and a 300-character component is `OSError: File name too long`
    rather than False. All of those were 500s, all of them are the caller's
    to fix, so all of them are a 400 (#270).

    Shared by the body and the header spellings -- `/v1/exec` reads `cwd`
    out of JSON, `/v1/exec/script` out of `X-Arena-Cwd`, and the fuzzer
    found the second one three commits after the first was fixed.
    """
    try:
        cwd = Path(raw or str(root)).expanduser()
        cwd = cwd if cwd.is_absolute() else root / cwd
        # Normalised here, not merely handed to the caller's check: `..` and
        # symlinks are resolved before anything looks at the path, so the
        # comparison below is between two real locations. CodeQL reads the
        # unresolved version as py/path-injection, and it is right to --
        # `under_root` arrives as a callback, which no analyser can follow.
        cwd = Path(os.path.realpath(cwd))
        # The sandbox boundary is checked before the filesystem is: saying
        # "does not exist" about a path outside the root answers a question
        # the caller is not allowed to ask (cubic).
        if under_root is not None and not _inside(cwd, root):
            return None, f"{OUTSIDE_ROOT} {root}"
        if under_root is not None and not under_root(cwd, root):
            return None, f"{OUTSIDE_ROOT} {root}"
        if not cwd.exists() or not cwd.is_dir():
            return None, f"cwd does not exist: {cwd}"
    except (OSError, RuntimeError, ValueError) as exc:
        return None, f"cwd is not a usable path ({type(exc).__name__})"
    return cwd, ""


def _inside(candidate: Path, root: Path) -> bool:
    """Whether `candidate` is `root` or something under it, both resolved.

    `os.path.commonpath` rather than a string prefix: `/rootless` starts
    with `/root` and is not inside it.
    """
    real_root = Path(os.path.realpath(root))
    try:
        return os.path.commonpath([str(candidate), str(real_root)]) == str(real_root)
    except ValueError:  # different drives on Windows
        return False


def requested_cwd(data: dict[str, Any], root: Path,
                  *, under_root: Callable[[Path, Path], bool] | None = None,
                  ) -> tuple[Path | None, str]:
    """`usable_cwd` for a JSON body.

    `body_str` refuses a `cwd` that is not a string first -- that raises
    past this function and becomes the usual field-named 400.
    """
    return usable_cwd(body_str(data, "cwd", default=""), root,
                      under_root=under_root)


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
    env = os.environ.copy()
    env.update(filter_caller_env(_caller_env(data)))
    return timeout, max_output, env


def _caller_env(data: dict[str, Any]) -> dict[str, Any]:
    """The `env` object the request sent, refused if it cannot be one.

    Three things a caller can send that used to end badly, all found on the
    #270 PR:

    * a string or an array, which the old `isinstance(raw, dict)` check
      silently replaced with `{}` -- the command then ran with a different
      environment than the caller asked for, and nothing said so;
    * a name containing `=`, which `subprocess` refuses with ValueError and
      the bridge reported as its own 500;
    * a NUL byte in a name or a value, same.

    All three are the caller's to fix, so all three are a 400 naming `env`.
    """
    raw = data.get("env")
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise BodyFieldError("env", raw, expected="an object")
    for key, value in raw.items():
        if "\x00" in f"{key}={value}":
            raise BodyFieldError(
                "env", raw, expected="an object without NUL bytes")
        if not str(key) or "=" in str(key):
            raise BodyFieldError(
                "env", raw, expected="an object whose names contain no '='")
    return dict(raw)
