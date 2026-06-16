"""CLI dispatcher for scripts/project_git.py."""
from __future__ import annotations

import argparse
import sys

from arena.project_cli.agents import agents_md_command
from arena.project_cli.issues import attach_report, issue_close, issue_list, issue_new, report
from arena.project_cli.projects import branch, commit, current, git_init, list_projects, log, new_project, status, use


def main() -> None:
    if len(sys.argv) > 1 and sys.argv[1] == "agents":
        raise SystemExit(agents_md_command(sys.argv[2:]))
    ap = argparse.ArgumentParser(); sub = ap.add_subparsers(dest="cmd", required=True)
    s=sub.add_parser("new"); s.add_argument("name"); s.add_argument("--description"); s.add_argument("--git", action="store_true"); s.set_defaults(func=new_project)
    s=sub.add_parser("use"); s.add_argument("name"); s.set_defaults(func=use)
    s=sub.add_parser("current"); s.set_defaults(func=current)
    s=sub.add_parser("list"); s.set_defaults(func=list_projects)
    s=sub.add_parser("git-init"); s.add_argument("name", nargs="?"); s.add_argument("-m","--message", default="Initial commit"); s.set_defaults(func=git_init)
    s=sub.add_parser("status"); s.add_argument("name", nargs="?"); s.set_defaults(func=status)
    s=sub.add_parser("commit"); s.add_argument("name", nargs="?"); s.add_argument("-m","--message", required=True); s.set_defaults(func=commit)
    s=sub.add_parser("log"); s.add_argument("name", nargs="?"); s.add_argument("-n","--limit", type=int, default=20); s.set_defaults(func=log)
    s=sub.add_parser("branch"); s.add_argument("name", nargs="?"); s.add_argument("--create"); s.add_argument("--checkout"); s.set_defaults(func=branch)
    s=sub.add_parser("issue-new"); s.add_argument("name", nargs="?"); s.add_argument("title"); s.add_argument("--body"); s.set_defaults(func=issue_new)
    s=sub.add_parser("issues"); s.add_argument("name", nargs="?"); s.set_defaults(func=issue_list)
    s=sub.add_parser("issue-close"); s.add_argument("name", nargs="?"); s.add_argument("id"); s.add_argument("--reason"); s.set_defaults(func=issue_close)
    s=sub.add_parser("attach-report"); s.add_argument("name", nargs="?"); s.add_argument("file"); s.set_defaults(func=attach_report)
    s=sub.add_parser("report"); s.add_argument("name", nargs="?"); s.set_defaults(func=report)
    a=ap.parse_args(); a.func(a)
