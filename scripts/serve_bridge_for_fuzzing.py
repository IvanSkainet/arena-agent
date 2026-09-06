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
* The failed-auth throttle is swept. Ten rejected requests from one address
  in a minute earn that address a 429 for the next minute, and the coverage
  phase sends unauthenticated requests on purpose -- so a few seconds in, the
  whole run turns into 429s and reports nothing. Measured: the first run
  written this way found six operations and the sweep found thirteen.

Both limiters keep their own tests; what is turned off here is their effect
on a fuzzer sharing one IP with itself.

The workspace root is a throwaway directory *and* the process changes into
it, which is not the same thing and the difference cost an afternoon. Parts
of the bridge resolve paths against the current working directory rather
than the configured root, so a run started from a checkout wrote
`missions/[None, None]/`, `queue/running/*.json` and -- once the fuzzer
reached the token endpoint -- a live `token.txt` into the repository. That
is #263 with a different author. The chdir keeps the mess inside the
temporary directory; the paths themselves are a separate defect with its own
issue.
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from aiohttp import web  # noqa: E402  -- after the path insert above

import arena.rate_limit as rate_limit  # noqa: E402
from tests._live_bridge import build_app  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8899)
    # Required rather than defaulted: a literal token in a script is a
    # credential in the source tree as far as any scanner is concerned, and
    # they are right often enough that arguing is not worth it. The caller
    # picks one; CI passes a throwaway.
    parser.add_argument("--token", required=True)
    args = parser.parse_args()

    rate_limit._rl_v2_config["enabled"] = False
    rate_limit._rate_limit_max = 10 ** 9

    # No --root option on purpose. It was there for a run against a fixed
    # directory, which nothing needs, and SonarCloud read it exactly right
    # (S8707): a path from the command line, handed to a bridge that then
    # writes files and executes commands relative to it, is a way out of the
    # sandbox for anything -- a person or an agent -- that gets the argument
    # wrong. A directory nobody can name cannot be escaped into.
    root = Path(tempfile.mkdtemp(prefix="fuzz-root-"))
    app = build_app(root, args.token)
    os.chdir(root)
    asyncio.run(_serve(app, args.port))
    return 0


async def _forget_failed_auth_attempts() -> None:
    """Keep the auth throttle from swallowing the run.

    It counts rejected requests per address over a minute and answers 429
    once there are ten. The fuzzer sends malformed and unauthenticated
    requests by design and all of them come from 127.0.0.1, so the counter
    is permanently over the line and the useful requests never arrive.
    """
    while True:
        with rate_limit._rate_limit_lock:
            for key in [k for k in rate_limit._rate_limit_store if k.startswith("auth_fail:")]:
                del rate_limit._rate_limit_store[key]
        await asyncio.sleep(1)


async def _serve(app: web.Application, port: int) -> None:
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, "127.0.0.1", port).start()
    sweeper = asyncio.create_task(_forget_failed_auth_attempts())
    print(f"bridge listening on 127.0.0.1:{port}", flush=True)
    try:
        while True:
            await asyncio.sleep(3600)
    finally:
        sweeper.cancel()


if __name__ == "__main__":
    raise SystemExit(main())
