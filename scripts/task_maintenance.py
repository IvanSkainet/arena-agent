#!/usr/bin/env python3
from __future__ import annotations
import argparse, datetime as dt, json, os, shutil, tarfile, uuid
from pathlib import Path
ROOT=Path(os.environ.get('ARENA_AGENT_HOME', str(Path.home()/'arena-agent'))).expanduser(); Q=ROOT/'queue'
INBOX=Q/'inbox'; RUNNING=Q/'running'; DONE=Q/'done'; FAILED=Q/'failed'
def now(): return dt.datetime.now(dt.timezone.utc)
def load(p): return json.loads(p.read_text(encoding='utf-8'))
def write(p,obj): p.write_text(json.dumps(obj, ensure_ascii=False, indent=2)+'\n', encoding='utf-8'); os.chmod(p,0o600)
def all_tasks():
    rows=[]
    for state,d in [('inbox',INBOX),('running',RUNNING),('done',DONE),('failed',FAILED)]:
        d.mkdir(parents=True, exist_ok=True)
        for p in d.glob('*.json'):
            try: obj=load(p)
            except Exception: obj={}
            rows.append((state,p,obj,p.stat().st_mtime))
    rows.sort(key=lambda x:x[3], reverse=True); return rows
def last(a):
    rows=all_tasks();
    if not rows: print('no tasks'); return
    state,p,obj,_=rows[0]
    print(json.dumps({'state':state,'path':str(p),'task':obj}, ensure_ascii=False, indent=2) if a.json else f"{state}\t{p.stem}\t{obj.get('exit_code','')}\t{obj.get('cmd','')}")
def retry(a):
    tid=a.id
    for state,d in [('failed',FAILED),('done',DONE),('running',RUNNING),('inbox',INBOX)]:
        p=d/f'{tid}.json'
        if p.exists():
            obj=load(p); break
    else: raise SystemExit(f'not found: {tid}')
    new_id=(a.new_id or (tid+'-retry-'+uuid.uuid4().hex[:6]))
    keep={k:obj.get(k) for k in ['cmd','cwd','timeout','max_output','env','notes'] if k in obj}
    keep.update({'id':new_id,'created_at':now().isoformat(timespec='seconds'),'retry_of':tid})
    INBOX.mkdir(parents=True, exist_ok=True); out=INBOX/f'{new_id}.json'; write(out,keep); print(str(out))
def clean(a):
    cutoff=now().timestamp()-a.days*86400; candidates=[]
    for d in [DONE,FAILED]:
        d.mkdir(parents=True, exist_ok=True)
        for p in d.glob('*.json'):
            if p.stat().st_mtime < cutoff: candidates.append(p)
    if not candidates: print('no old tasks'); return
    archive=Q/f'tasks-archive-{now().strftime("%Y%m%dT%H%M%SZ")}.tgz'
    with tarfile.open(archive,'w:gz') as tar:
        for p in candidates: tar.add(p, arcname=str(p.relative_to(Q)))
    os.chmod(archive,0o600)
    if a.yes:
        for p in candidates: p.unlink()
    print(json.dumps({'archive':str(archive),'candidates':len(candidates),'deleted':bool(a.yes)}, ensure_ascii=False, indent=2))
def main():
    ap=argparse.ArgumentParser(); sub=ap.add_subparsers(dest='cmd', required=True)
    s=sub.add_parser('last'); s.add_argument('--json', action='store_true'); s.set_defaults(func=last)
    s=sub.add_parser('retry'); s.add_argument('id'); s.add_argument('--new-id'); s.set_defaults(func=retry)
    s=sub.add_parser('clean'); s.add_argument('--days', type=float, default=7); s.add_argument('--yes', action='store_true'); s.set_defaults(func=clean)
    a=ap.parse_args(); a.func(a)
if __name__=='__main__': main()
