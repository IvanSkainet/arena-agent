#!/usr/bin/env python3
"""Run the bridge on a port so a fuzzer can talk to it (#258).

The fuzzing gate needs the real application answering real HTTP, not the
in-process TestClient the contract sweeps use: Schemathesis reads the
document from `/openapi.json` and then sends thousands of requests to the
same host. This is the one place that setup is written down, so CI and a
laptop run the same bridge.

Two deliberate differences from a production bridge, both about making the
run mean something:

* The per-IP rate limiter is off. It allows 300 requests a minute; a fuzz
  run sends thousands from one address, so the limiter answers 429 for most
  of them and the run comes back green having tested almost nothing. The
  limiter itself is covered by its own tests.
* The token is fixed and passed in, and the profile is `owner-shell`, so the
  fuzzer reaches the handlers rather than bouncing off the 401 wall. An
  operation that only ever answers 401 is an operation that never got tested.
* The failed-auth throttle cannot accumulate. Ten rejected requests from one
  address in a minute earn that address a 429 for the next minute, and the
  coverage phase sends unauthenticated requests on purpose -- so a few
  seconds in the whole run turns into 429s and reports nothing. Measured:
  the run written without this found six operations where the same run with
  it found thirteen.

Both limiters keep their own tests; what is turned off here is their effect
on a fuzzer sharing one IP with itself.

Keeping the run out of the checkout takes three things, and it took three
attempts to find that out: a throwaway workspace, a chdir into it (parts of
the bridge resolve paths against the current working directory), and
`ARENA_AGENT_HOME` plus three `arena.constants` values set before the bridge
is imported -- `TOKEN_FILE` is `Path(__file__).parent.parent / "token.txt"`,
which no chdir can move. Without all three, a run that reaches POST
/v1/token/regenerate writes a live token next to the source, and one that
reaches the mission endpoints leaves `missions/[None, None]/` and
`queue/running/*.json` behind. That is #263 with a different author; the
paths themselves are #276.
"""
from __future__ import annotations

import argparse
import asyncio
import atexit
import contextlib
import os
import shutil
import signal
import sys
import tempfile
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from aiohttp import web

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

# Named rather than sprinkled through the code (corgea): the port the job
# and the config agree on, a request ceiling high enough that the limiter
# never fires during a run, and the interval the idle loop naps for.
DEFAULT_PORT = 8899
NO_RATE_LIMIT = 10 ** 9
IDLE_SLEEP_S = 3600


class _NoFailedAuthMemory(dict):
    """A rate-limit store that refuses to remember failed authentication.

    `require_auth` keeps a list of timestamps per `auth_fail:<peer>` key and
    answers 429 once it holds ten within a minute. Every fuzz request comes
    from 127.0.0.1 and the coverage phase sends unauthenticated ones on
    purpose, so the list is over the line within seconds and the rest of the
    run measures the throttle rather than the handlers.

    Dropping the writes rather than clearing them on a timer: a sweeper
    running once a second still loses to four workers, and "usually
    isolated" is the kind of gate that passes for the wrong reason (cubic).
    Every other key behaves normally.
    """

    def __setitem__(self, key: str, value: Any) -> None:
        if not str(key).startswith("auth_fail:"):
            super().__setitem__(key, value)

    def __getitem__(self, key: str) -> Any:
        if str(key).startswith("auth_fail:"):
            return []
        return super().__getitem__(key)

    def __contains__(self, key: object) -> bool:
        if str(key).startswith("auth_fail:"):
            return True  # "already there", so nothing initialises it
        return super().__contains__(key)


def _point_the_bridge_at(root: Path) -> None:
    """Redirect every path the bridge derives, before it derives them.

    Import order is the whole mechanism, which is why the bridge is imported
    inside `main` and not at the top of this file: `arena.constants` is read
    when the runtime namespace is built, and `runtime_deps.core` binds
    `_rate_limit_store` by name at the same moment, so anything done after
    that import reaches nobody. Importing this module used to have those
    side effects; now nothing happens until `main` runs (corgea).

    `ARENA_AGENT_HOME` moves queue/, missions/, reports/ and skills/ -- the
    supported way. The three constants below hang off the source tree
    instead of the workspace, so neither that variable nor a chdir moves
    them, and a fuzz run that reaches POST /v1/token/regenerate would write
    a live token next to the source without this.
    """
    os.environ["ARENA_AGENT_HOME"] = str(root)

    import arena.constants as constants
    import arena.rate_limit as rate_limit

    constants.APP_DIR = root
    constants.TOKEN_FILE = root / "token.txt"
    constants.AUDIT = root / "audit.jsonl"

    # Both limiters, off for the duration: the per-IP one allows 300 requests
    # a minute against a run that sends thousands, and the failed-auth
    # throttle answers 429 to an address after ten rejections, which the
    # coverage phase produces on purpose. Reaching into another module's
    # private names is not something to do lightly; it is done here because
    # the alternative -- a configuration switch that only the fuzz job would
    # ever use -- would put test-only behaviour into the bridge itself.
    rate_limit._rl_v2_config["enabled"] = False
    rate_limit._rate_limit_max = NO_RATE_LIMIT
    rate_limit._rate_limit_store = _NoFailedAuthMemory()


def _prepare_workspace(root: Path) -> None:
    """Create the directory layout a real installation already has.

    `tests/_live_bridge.build_app` clears the startup hooks -- the contract
    sweeps do not want background workers -- and one of those hooks is what
    creates `memory/` and initialises the fact database. That went unnoticed
    while the workspace was the checkout, which has the directories in it;
    pointing the run at an empty temporary root turned four endpoints into
    `OperationalError: unable to open database file`, and the gate would
    have reported them as defects in the bridge.
    """
    from arena.memory.schema import init_memory_db
    from arena.paths import ArenaPaths

    paths = ArenaPaths.from_env(root)
    for directory in (paths.queue, paths.inbox, paths.running, paths.done,
                      paths.failed, paths.skills_dir, paths.hooks_dir,
                      paths.agents_dir, paths.subagents_dir,
                      paths.missions_dir, paths.reports_dir,
                      paths.memory_file.parent):
        directory.mkdir(parents=True, exist_ok=True)
    init_memory_db(db_path=paths.memory_db, jsonl_path=paths.memory_file)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    # Read from the environment, not from argv: a token on the command line
    # is readable from /proc/<pid>/cmdline by anything else on the runner
    # for the whole job (cubic). Still no default -- a literal token in a
    # script is a credential in the source tree as far as any scanner is
    # concerned, and they are right often enough that arguing is not worth
    # it. `--token` stays for a laptop run, where argv is not a boundary.
    parser.add_argument("--token", default=os.environ.get("ARENA_FUZZ_TOKEN", ""))
    args = parser.parse_args()
    if not args.token:
        parser.error("set ARENA_FUZZ_TOKEN or pass --token")

    started_in = Path.cwd()
    # Handler first, then the workspace with the signal held off. A
    # pid-derived name closed the SIGTERM window but opened a worse hole
    # (cubic, twice): the directory holds `token.txt`, the audit log and
    # every `ARENA_AGENT_HOME` file, so it has to be 0o700 and it has to
    # have a name no other local user can guess ahead of the run.
    # `mkdtemp` gives both; blocking SIGTERM across the two statements
    # gives what the pid name was for.
    _stop_on_sigterm()
    with _sigterm_held():
        root = Path(tempfile.mkdtemp(prefix="fuzz-root-"))
        _LEAKED.append(root)
    # Everything after the directory exists is inside the try, including the
    # redirection and the import that follows it: both can raise, and a
    # cleanup that starts later leaves one workspace per failed start
    # (sourcery and cubic, separately).
    try:
        return _serve_until_stopped(root, args)
    except KeyboardInterrupt:
        # Ctrl-C or the SIGTERM handler above. Not an error: the job stops
        # this process when the fuzz run finishes, and a traceback in the
        # log would read like one.
        print("bridge stopped", flush=True)
        return 0
    finally:
        # Cleanup first, chdir second, and the chdir is allowed to fail: the
        # directory the caller started in can disappear while the bridge
        # runs, and losing the workspace because of that would be the more
        # expensive half (cubic). Back to where the caller was rather than
        # to the repository root -- this script can be started anywhere, and
        # moving the process somewhere it never was is a surprise (corgea).
        shutil.rmtree(root, ignore_errors=True)
        if root in _LEAKED:
            _LEAKED.remove(root)
        with contextlib.suppress(OSError):
            os.chdir(started_in)


def _serve_until_stopped(root: Path, args: argparse.Namespace) -> int:
    """The run itself, with the workspace already created."""
    _point_the_bridge_at(root)
    from tests._live_bridge import build_app

    # No --root option on purpose. It was there for a run against a fixed
    # directory, which nothing needs, and SonarCloud read it exactly right
    # (S8707): a path from the command line, handed to a bridge that then
    # writes files and executes commands relative to it, is a way out of the
    # sandbox for anything -- a person or an agent -- that gets the argument
    # wrong. A directory nobody can name cannot be escaped into.
    _prepare_workspace(root)
    app = build_app(root, args.token)
    os.chdir(root)
    asyncio.run(_serve(app, args.port))
    return 0


# Workspaces created but not yet handed to a `finally`. One entry at a time
# in practice; a list because atexit has to read it without knowing when.
_LEAKED: list[Path] = []


@contextlib.contextmanager
def _sigterm_held() -> Iterator[None]:
    """Delay SIGTERM until the block finishes.

    The gap between `mkdtemp` returning and the path being recorded is two
    bytecodes wide and still real: a signal landing in it raises out of a
    frame that knows the directory, into cleanup that does not, and the
    workspace stays on disk (cubic). Blocking the signal makes the pair
    atomic as far as the handler is concerned; a SIGTERM that arrives
    meanwhile is delivered on the way out.

    POSIX only. On Windows `pthread_sigmask` does not exist and CI does not
    send SIGTERM there, so the block is a no-op rather than an error.
    """
    mask = getattr(signal, "pthread_sigmask", None)
    if mask is None:
        yield
        return
    mask(signal.SIG_BLOCK, {signal.SIGTERM})
    try:
        yield
    finally:
        mask(signal.SIG_UNBLOCK, {signal.SIGTERM})


@atexit.register
def _remove_any_leaked_workspace() -> None:
    """Last resort for a workspace whose owner never reached its cleanup."""
    while _LEAKED:
        shutil.rmtree(_LEAKED.pop(), ignore_errors=True)


def _stop_on_sigterm() -> None:
    """Turn SIGTERM into KeyboardInterrupt so the cleanup runs.

    CI stops this process with SIGTERM, whose default action is immediate
    termination -- no `finally`, no `runner.cleanup()`, one temporary
    workspace left behind per run (sourcery and cubic). Raising instead
    gives asyncio a chance to unwind.
    """
    def _raise(signum: int, frame: object) -> None:  # noqa: ARG001
        raise KeyboardInterrupt(f"signal {signum}")

    try:
        signal.signal(signal.SIGTERM, _raise)
    except ValueError:
        # Only reachable off the main thread, where the interpreter refuses
        # to install handlers. Silence would be wrong: the workspace cleanup
        # depends on this handler, and a run without it leaks a directory
        # per SIGTERM with nothing in the log to say why (corgea).
        print(
            "warning: SIGTERM handler not installed (not the main thread); "
            "a terminated run may leave its workspace behind",
            file=sys.stderr, flush=True,
        )


async def _serve(app: web.Application, port: int) -> None:
    """Serve until interrupted, then shut the runner down properly.

    The loop has no exit of its own -- the job kills the process when the
    fuzz run finishes -- but Ctrl-C and SIGTERM arrive as CancelledError or
    KeyboardInterrupt, and without the cleanup aiohttp leaves the socket and
    its connections to the garbage collector (corgea).
    """
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, "127.0.0.1", port).start()
    print(f"bridge listening on 127.0.0.1:{port}", flush=True)
    try:
        while True:
            await asyncio.sleep(IDLE_SLEEP_S)
    finally:
        await runner.cleanup()


if __name__ == "__main__":
    raise SystemExit(main())
