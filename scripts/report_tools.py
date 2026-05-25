#!/usr/bin/env python3
from __future__ import annotations
import argparse, datetime as dt, json, mimetypes, os
from pathlib import Path
ROOT=Path(os.environ.get('ARENA_AGENT_HOME', str(Path.home()/'arena-agent'))).expanduser(); REPORTS=ROOT/'reports'
def items(limit=None):
    REPORTS.mkdir(parents=True, exist_ok=True)
    rows=[]
    for p in REPORTS.iterdir():
        if p.is_file():
            st=p.stat(); rows.append({'name':p.name,'path':str(p),'size':st.st_size,'mtime':dt.datetime.fromtimestamp(st.st_mtime, dt.timezone.utc).isoformat(timespec='seconds'),'type':mimetypes.guess_type(str(p))[0] or 'application/octet-stream'})
    rows.sort(key=lambda x:x['mtime'], reverse=True)
    return rows[:limit] if limit else rows
def list_cmd(a):
    rows=items(a.limit)
    if a.json: print(json.dumps({'ok':True,'reports':rows}, ensure_ascii=False, indent=2)); return
    for r in rows: print(f"{r['mtime']}\t{r['size']}\t{r['name']}")
def index_cmd(a):
    rows=items(None); out=REPORTS/'INDEX.md'
    lines=['# Arena Agent Reports Index','',f'Generated: {dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")}','', '| Time | Size | File | Type |','|---|---:|---|---|']
    for r in rows:
        lines.append(f"| {r['mtime']} | {r['size']} | [{r['name']}](./{r['name']}) | {r['type']} |")
    out.write_text('\n'.join(lines)+'\n', encoding='utf-8'); os.chmod(out,0o600); print(str(out))
def latest_cmd(a):
    rows=items(None)
    if a.pattern: rows=[r for r in rows if a.pattern in r['name']]
    if not rows: raise SystemExit('no reports')
    print(rows[0]['path'])
def main():
    ap=argparse.ArgumentParser(); sub=ap.add_subparsers(dest='cmd', required=True)
    s=sub.add_parser('list'); s.add_argument('--limit', type=int, default=50); s.add_argument('--json', action='store_true'); s.set_defaults(func=list_cmd)
    s=sub.add_parser('index'); s.set_defaults(func=index_cmd)
    s=sub.add_parser('latest'); s.add_argument('pattern', nargs='?'); s.set_defaults(func=latest_cmd)
    a=ap.parse_args(); a.func(a)
if __name__=='__main__': main()
