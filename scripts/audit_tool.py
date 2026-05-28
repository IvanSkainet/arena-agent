#!/usr/bin/env python3
from __future__ import annotations
import argparse, collections, datetime as dt, json, os, shutil
from pathlib import Path
AUDIT = Path.home() / 'arena-bridge' / 'audit.jsonl'

def read_events(limit: int | None = None):
    if not AUDIT.exists():
        return []
    lines = AUDIT.read_text(encoding='utf-8', errors='replace').splitlines()
    if limit:
        lines = lines[-limit:]
    events=[]
    for line in lines:
        try: events.append(json.loads(line))
        except Exception: events.append({'raw': line})
    return events

def tail(args):
    for e in read_events(args.lines):
        if args.json:
            print(json.dumps(e, ensure_ascii=False))
        else:
            ts=e.get('ts','')
            typ=e.get('type','')
            rid=e.get('request_id','')
            code=e.get('exit_code','')
            dur=e.get('duration','')
            trunc=' truncated' if e.get('cmd_truncated') or e.get('truncated') else ''
            cmd=str(e.get('cmd','')).replace('\n',' ')[:args.cmd_chars]
            print(f'{ts}\t{typ}\t{code}\t{dur}\t{rid}{trunc}\t{cmd}')

def stats(args):
    events=read_events(None)
    by_type=collections.Counter(e.get('type','unknown') for e in events)
    exit_codes=collections.Counter(str(e.get('exit_code')) for e in events if 'exit_code' in e)
    truncated=sum(1 for e in events if e.get('cmd_truncated') or e.get('truncated'))
    print(json.dumps({
        'ok': True,
        'audit': str(AUDIT),
        'events': len(events),
        'by_type': dict(by_type),
        'exit_codes': dict(exit_codes),
        'truncated_events': truncated,
        'size_bytes': AUDIT.stat().st_size if AUDIT.exists() else 0,
    }, ensure_ascii=False, indent=2))

def rotate(args):
    if not AUDIT.exists():
        print('no audit file')
        return
    ts=dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    dest=AUDIT.with_name(f'audit-{ts}.jsonl')
    shutil.move(str(AUDIT), str(dest))
    AUDIT.touch(mode=0o600, exist_ok=True)
    os.chmod(dest, 0o600)
    os.chmod(AUDIT, 0o600)
    print(str(dest))

def main():
    p=argparse.ArgumentParser()
    sub=p.add_subparsers(dest='cmd', required=True)
    s=sub.add_parser('tail'); s.add_argument('--lines', type=int, default=50); s.add_argument('--json', action='store_true'); s.add_argument('--cmd-chars', type=int, default=240); s.set_defaults(func=tail)
    s=sub.add_parser('stats'); s.set_defaults(func=stats)
    s=sub.add_parser('rotate'); s.set_defaults(func=rotate)
    args=p.parse_args(); args.func(args)
if __name__=='__main__': main()
