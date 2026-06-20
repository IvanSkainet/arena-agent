"""CLI dispatcher for scripts/memory.py."""
from __future__ import annotations

import argparse
import sys

from arena.memory.cli_commands import recall, remember


def main() -> int:
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("remember")
    s.add_argument("key")
    s.add_argument("rest", nargs=argparse.REMAINDER)
    s.add_argument("--profile", default="default")
    s.set_defaults(func=remember)

    s = sub.add_parser("recall")
    s.add_argument("query", nargs="?")
    s.add_argument("--limit", type=int, default=50)
    s.add_argument("--profile", default="default")
    s.set_defaults(func=recall)

    args = p.parse_args()
    try:
        return int(args.func(args) or 0)
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
