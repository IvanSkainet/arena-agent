#!/usr/bin/env python3
from __future__ import annotations
import argparse, os
from pathlib import Path
ROOT=Path(os.environ.get('ARENA_AGENT_HOME', str(Path.home() / 'arena-bridge'))).expanduser(); SK=ROOT/'skills'
def list_skills(args):
    for p in sorted(SK.rglob('*.md')): print(str(p.relative_to(SK)).removesuffix('.md'))
def show(args):
    name=args.name.strip().removesuffix('.md')+'.md'
    for p in SK.rglob(name): print(p.read_text(encoding='utf-8')); return
    p=SK/(args.name+'.md')
    if p.exists(): print(p.read_text(encoding='utf-8')); return
    raise SystemExit('skill not found')
def main():
    ap=argparse.ArgumentParser(); sub=ap.add_subparsers(dest='cmd', required=True)
    s=sub.add_parser('list'); s.set_defaults(func=list_skills)
    s=sub.add_parser('show'); s.add_argument('name'); s.set_defaults(func=show)
    a=ap.parse_args(); a.func(a)
if __name__=='__main__': main()
