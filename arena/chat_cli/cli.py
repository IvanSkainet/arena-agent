"""CLI for agentctl chat."""
from __future__ import annotations

import argparse

from arena.chat_cli.repl import repl


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--session", help="session name slug")
    args = ap.parse_args()
    repl(args.session)
    return 0
