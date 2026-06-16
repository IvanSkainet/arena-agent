"""CLI dispatcher for mcp_marketplace.py."""
from __future__ import annotations

import argparse

from arena.mcp_marketplace.commands import cmd_install, cmd_list, cmd_registry, cmd_remove, cmd_test


def main() -> int:
    ap = argparse.ArgumentParser(prog="mcp_marketplace")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("registry").set_defaults(func=cmd_registry)
    s = sub.add_parser("install"); s.add_argument("name"); s.set_defaults(func=cmd_install)
    s = sub.add_parser("remove"); s.add_argument("name"); s.set_defaults(func=cmd_remove)
    sub.add_parser("list").set_defaults(func=cmd_list)
    s = sub.add_parser("test"); s.add_argument("name"); s.set_defaults(func=cmd_test)
    args = ap.parse_args()
    return args.func(args) or 0
