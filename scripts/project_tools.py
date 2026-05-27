#!/usr/bin/env python3
from __future__ import annotations
import argparse, datetime as dt, json, os
from pathlib import Path
ROOT=Path(os.environ.get('ARENA_AGENT_HOME', str(Path.home() / 'arena-bridge'))).expanduser(); PROJECTS=ROOT/'projects'
def now(): return dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds')
def safe(name):
    s=''.join(c if c.isalnum() or c in '-_.' else '-' for c in name.strip())
    if not s or s.startswith('.'): raise SystemExit('bad project name')
    return s
def new(args):
    name=safe(args.name); p=PROJECTS/name; p.mkdir(parents=True, exist_ok=True)
    for d in ['data','src','reports','notes','tmp']: (p/d).mkdir(exist_ok=True)
    meta=p/'project.json'
    if not meta.exists(): meta.write_text(json.dumps({'name':name,'created_at':now(),'description':args.description or ''}, ensure_ascii=False, indent=2)+'\n')
    readme=p/'README.md'
    if not readme.exists(): readme.write_text(f'# {name}\n\nCreated: {now()}\n\n{args.description or ""}\n')
    print(str(p))
def listp(args):
    PROJECTS.mkdir(parents=True, exist_ok=True)
    for p in sorted(x for x in PROJECTS.iterdir() if x.is_dir()): print(p.name)
def status(args):
    p=PROJECTS/safe(args.name)
    if not p.exists(): raise SystemExit('not found')
    files=[]
    for x in sorted(p.rglob('*')):
        if x.is_file(): files.append({'path':str(x.relative_to(p)), 'size':x.stat().st_size})
    print(json.dumps({'ok':True,'project':p.name,'path':str(p),'files':files[:500]}, ensure_ascii=False, indent=2))
def report(args):
    p=PROJECTS/safe(args.name)
    if not p.exists(): raise SystemExit('not found')
    out=p/'reports'/f'project-report-{dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")}.md'
    lines=[f'# Project report: {p.name}','',f'Generated: {now()}','', '## Files','']
    for x in sorted(p.rglob('*')):
        if x.is_file(): lines.append(f'- `{x.relative_to(p)}` ({x.stat().st_size} bytes)')
    out.write_text('\n'.join(lines)+'\n'); print(str(out))
def main():
    ap=argparse.ArgumentParser(); sub=ap.add_subparsers(dest='cmd', required=True)
    s=sub.add_parser('new'); s.add_argument('name'); s.add_argument('--description'); s.set_defaults(func=new)
    s=sub.add_parser('list'); s.set_defaults(func=listp)
    s=sub.add_parser('status'); s.add_argument('name'); s.set_defaults(func=status)
    s=sub.add_parser('report'); s.add_argument('name'); s.set_defaults(func=report)
    a=ap.parse_args(); a.func(a)
if __name__=='__main__': main()
