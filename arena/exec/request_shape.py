"""What an exec request asked for, once the body has been checked.

Two readers, split out of `handlers.py` because that module crossed the
600-line ceiling in `test_architecture_boundaries.py` when #270 added the
validation, and because both are pure functions of the body: no request, no
response, no context beyond the numbers on it.
"""
from __future__ import annotations

import os
from collections.abc import Callable
from pathlib import Path, PurePosixPath
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
        if under_root is None:
            # `allow_any_cwd`, the owner profile: going outside the root is
            # the point of it, and the caller already has a shell here.
            cwd = _anywhere(raw, root)
        else:
            # Everyone else gets a path *rebuilt* inside the root rather
            # than checked afterwards. Three attempts at "build it, then
            # compare" -- callback, helper, inline realpath -- were all
            # correct and all still py/path-injection to CodeQL, because a
            # comparison is not a construction. This cannot leave the root:
            # the components are filtered, then joined onto it.
            cwd = _inside_root(raw, root)
            if cwd is None:
                return None, f"{OUTSIDE_ROOT} {root}"
        if under_root is not None and not under_root(cwd, root):
            return None, f"{OUTSIDE_ROOT} {root}"
        if not cwd.exists() or not cwd.is_dir():
            return None, f"cwd does not exist: {cwd}"
    except (OSError, RuntimeError, ValueError) as exc:
        return None, f"cwd is not a usable path ({type(exc).__name__})"
    return cwd, ""


def _anywhere(raw: str, root: Path) -> Path:
    """The path as asked for, for the profile that allows any directory."""
    asked = Path(raw or str(root)).expanduser()
    return asked if asked.is_absolute() else root / asked


def _inside_root(raw: str, root: Path) -> Path | None:
    """`raw` rebuilt under `root`, or None if it was never going to be.

    Built rather than validated: every component is checked before it is
    joined, so there is no moment at which a path outside the root exists.
    `..` and absolute components are refused rather than normalised away --
    a caller who wrote `../x` meant something this profile does not allow,
    and quietly reinterpreting it would be worse than saying no.
    """
    parts = _relative_parts(raw, root)
    if parts is None:
        return None
    built = root
    for part in parts:
        built = built / part
    return built


def _relative_parts(raw: str, root: Path) -> list[str] | None:
    """The components of `raw` relative to `root`, or None if it escapes.

    An absolute request is allowed only when it already names somewhere
    under the root; what comes back is the remainder, so the join above
    starts from the root either way.
    """
    if raw.startswith("/") or (len(raw) > 1 and raw[1] == ":"):
        try:
            return list(PurePosixPath(raw).relative_to(PurePosixPath(str(root))).parts)
        except ValueError:
            return None
    asked = PurePosixPath(raw.replace("\\", "/")) if raw else PurePosixPath()
    parts = [part for part in asked.parts if part not in (".", "/")]
    if any(part == ".." or part.startswith("~") for part in parts):
        return None
    return parts


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
        _check_env_pair(raw, str(key), f"{key}={value}")
    return dict(raw)


def _check_env_pair(raw: dict[str, Any], name: str, pair: str) -> None:
    """One name/value pair, refused if `subprocess` would reject it."""
    if "\x00" in pair:
        raise BodyFieldError("env", raw, expected="an object without NUL bytes")
    if not name or "=" in name:
        raise BodyFieldError(
            "env", raw, expected="an object whose names contain no '='")
