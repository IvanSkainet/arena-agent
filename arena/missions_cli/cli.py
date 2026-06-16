"""CLI dispatcher for mission_manager.py."""
from __future__ import annotations

from arena.missions_cli.common import *  # noqa: F401,F403
from arena.missions_cli.commands import *  # noqa: F401,F403

def main():
    ap=argparse.ArgumentParser(); sub=ap.add_subparsers(dest='cmd',required=True)
    s=sub.add_parser('list'); s.add_argument('--missions',action='store_true'); s.set_defaults(func=list_cmd)
    s=sub.add_parser('show'); s.add_argument('name'); s.set_defaults(func=show_cmd)
    s=sub.add_parser('new'); s.add_argument('template'); s.add_argument('--name'); s.set_defaults(func=new_cmd)
    s=sub.add_parser('check'); s.add_argument('name'); s.set_defaults(func=check_cmd)
    s=sub.add_parser('status'); s.add_argument('id'); s.set_defaults(func=status_cmd)
    s=sub.add_parser('run'); s.add_argument('id'); s.add_argument('--step',type=int); s.add_argument('--timeout',type=int,default=180); s.set_defaults(func=run_cmd_mission)
    s=sub.add_parser('report'); s.add_argument('id'); s.set_defaults(func=report_cmd)
    s=sub.add_parser('stress'); s.set_defaults(func=stress_cmd)
    s=sub.add_parser('roadmap'); s.set_defaults(func=roadmap_cmd)
    a=ap.parse_args(); a.func(a)
