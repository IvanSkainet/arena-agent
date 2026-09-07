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
import os
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

# Everything below imports the bridge, and the bridge reads its paths at
# import time, so the redirection has to happen first.
# Named rather than sprinkled through the code (corgea): the port the job
# and the config agree on, a request ceiling high enough that the limiter
# never fires during a run, and the interval the idle loop naps for.
DEFAULT_PORT = 8899
NO_RATE_LIMIT = 10 ** 9
IDLE_SLEEP_S = 3600

FUZZ_ROOT = Path(tempfile.mkdtemp(prefix="fuzz-root-"))

# `ArenaPaths.from_env` reads this, and queue/, missions/, reports/ and
# skills/ all follow from it. The supported way to move the workspace.
os.environ["ARENA_AGENT_HOME"] = str(FUZZ_ROOT)

import arena.constants as constants  # noqa: E402
import arena.rate_limit as rate_limit  # noqa: E402

# The three ArenaPaths does not cover: they hang off the source tree rather
# than the workspace, so neither the variable above nor a chdir moves them.
constants.APP_DIR = FUZZ_ROOT
constants.TOKEN_FILE = FUZZ_ROOT / "token.txt"
constants.AUDIT = FUZZ_ROOT / "audit.jsonl"


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


# Rebound before the bridge is imported: `runtime_deps.core` does
# `from arena.rate_limit import _rate_limit_store`, and the runtime namespace
# is built from that module at import time, so a later rebinding reaches
# nobody -- which is how the first attempt still answered 429.
rate_limit._rate_limit_store = _NoFailedAuthMemory()

from aiohttp import web  # noqa: E402

from arena.memory.schema import init_memory_db  # noqa: E402
from arena.paths import ArenaPaths  # noqa: E402
from tests._live_bridge import build_app  # noqa: E402


def _prepare_workspace() -> None:
    """Create the directory layout a real installation already has.

    `tests/_live_bridge.build_app` clears the startup hooks -- the contract
    sweeps do not want background workers -- and one of those hooks is what
    creates `memory/` and initialises the fact database. That went unnoticed
    while the workspace was the checkout, which has the directories in it;
    pointing the run at an empty temporary root turned four endpoints into
    `OperationalError: unable to open database file`, and the gate would
    have reported them as defects in the bridge.
    """
    paths = ArenaPaths.from_env(FUZZ_ROOT)
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
    # Required rather than defaulted: a literal token in a script is a
    # credential in the source tree as far as any scanner is concerned, and
    # they are right often enough that arguing is not worth it. The caller
    # picks one; CI passes a throwaway.
    parser.add_argument("--token", required=True)
    args = parser.parse_args()

    rate_limit._rl_v2_config["enabled"] = False
    rate_limit._rate_limit_max = NO_RATE_LIMIT

    # No --root option on purpose. It was there for a run against a fixed
    # directory, which nothing needs, and SonarCloud read it exactly right
    # (S8707): a path from the command line, handed to a bridge that then
    # writes files and executes commands relative to it, is a way out of the
    # sandbox for anything -- a person or an agent -- that gets the argument
    # wrong. A directory nobody can name cannot be escaped into.
    # The whole body is inside the try, not just the serving: preparing the
    # workspace, building the app and the chdir can all fail, and each of
    # them leaves the temporary directory behind if the cleanup only covers
    # what comes after (CodeRabbit).
    try:
        _prepare_workspace()
        app = build_app(FUZZ_ROOT, args.token)
        os.chdir(FUZZ_ROOT)
        asyncio.run(_serve(app, args.port))
    finally:
        # One abandoned workspace per run fills /tmp on a laptop (cubic).
        os.chdir(REPO_ROOT)
        shutil.rmtree(FUZZ_ROOT, ignore_errors=True)
    return 0


async def _serve(app: web.Application, port: int) -> None:
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, "127.0.0.1", port).start()
    print(f"bridge listening on 127.0.0.1:{port}", flush=True)
    while True:
        await asyncio.sleep(IDLE_SLEEP_S)


if __name__ == "__main__":
    raise SystemExit(main())
