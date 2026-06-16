"""CLI dispatcher for skill_runner.py."""
from __future__ import annotations

import argparse

from arena.skills.cli_listing import list_skills, path_skill, show_skill
from arena.skills.cli_new import new_skill
from arena.skills.cli_run import run_skill


def main() -> int:
    ap = argparse.ArgumentParser(prog="agentctl skill")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("list").set_defaults(func=list_skills)

    s = sub.add_parser("show")
    s.add_argument("name")
    s.set_defaults(func=show_skill)

    s = sub.add_parser("path")
    s.add_argument("name")
    s.set_defaults(func=path_skill)

    s = sub.add_parser("run")
    s.add_argument("name")
    s.add_argument("--timeout", type=int, default=0)
    s.add_argument("skill_args", nargs=argparse.REMAINDER)
    s.set_defaults(func=run_skill)

    s = sub.add_parser("new")
    s.add_argument("name", help="namespace/name, e.g. core/digest")
    s.set_defaults(func=new_skill)

    args = ap.parse_args()
    return args.func(args) or 0
