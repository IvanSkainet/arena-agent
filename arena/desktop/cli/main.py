"""CLI dispatcher for scripts/desktop_manager.py."""
from __future__ import annotations

from arena.desktop.cli.common import *  # noqa: F401,F403
from arena.desktop.cli.input import click, key, move, type_text
from arena.desktop.cli.screens import info, ocr, shot, windows

def main():
    ap=argparse.ArgumentParser(); sub=ap.add_subparsers(dest='cmd',required=True)
    sub.add_parser('info').set_defaults(func=info)
    s=sub.add_parser('shot'); s.add_argument('path',nargs='?'); s.set_defaults(func=shot)
    s=sub.add_parser('ocr'); s.add_argument('image',nargs='?'); s.add_argument('--lang',default='eng+rus'); s.set_defaults(func=ocr)
    sub.add_parser('windows').set_defaults(func=windows)
    s=sub.add_parser('move'); s.add_argument('x'); s.add_argument('y'); s.add_argument('--steps',default=25); s.add_argument('--delay',default=.01); s.set_defaults(func=move)
    s=sub.add_parser('click'); s.add_argument('x'); s.add_argument('y'); s.add_argument('--button',default='1'); s.add_argument('--steps',default=25); s.add_argument('--delay',default=.01); s.set_defaults(func=click)
    s=sub.add_parser('key'); s.add_argument('key'); s.set_defaults(func=key)
    s=sub.add_parser('type'); s.add_argument('text'); s.set_defaults(func=type_text)
    a=ap.parse_args(); a.func(a)
