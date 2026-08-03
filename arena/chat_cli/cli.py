"""CLI for agentctl chat."""
from __future__ import annotations

import argparse

from arena.chat_cli.common import open_session
from arena.chat_cli.repl import repl

# The REPL understands these; /mode in-session accepts the same set.
MODES = ("safe", "edit", "full")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--session", help="session name slug")
    ap.add_argument("--mode", choices=MODES, default="safe",
                    help="starting permission mode (default: safe)")
    args = ap.parse_args()
    # Two defects fixed here, both of which made `scripts/chat.py` raise on
    # every single run:
    #   * `mode` is a required parameter of repl() and was never passed;
    #   * repl() wants the session Path, not the raw --session slug. The slug
    #     has to go through open_session(), which creates the .jsonl and
    #     repoints the `current` symlink.
    return repl(open_session(args.session), args.mode)
