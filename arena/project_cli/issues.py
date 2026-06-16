"""Project issue/report commands."""
from __future__ import annotations

from arena.project_cli.common import *  # noqa: F401,F403

def issue_new(args):
    p=project_path(args.name); d=p/'issues/open'; d.mkdir(parents=True, exist_ok=True); iid=dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-'+uuid.uuid4().hex[:6]
    obj={'id':iid,'title':args.title,'body':args.body or '','state':'open','created_at':now()}
    (d/f'{iid}.json').write_text(json.dumps(obj,ensure_ascii=False,indent=2)+'\n',encoding='utf-8'); (d/f'{iid}.md').write_text(f"# {args.title}\n\nID: {iid}\nCreated: {obj['created_at']}\n\n{obj['body']}\n",encoding='utf-8')
    print(iid)

def issue_list(args):
    p=project_path(args.name); rows=[]
    for state in ['open','closed']:
        for f in (p/'issues'/state).glob('*.json'):
            try: obj=json.loads(f.read_text()); rows.append((state,obj))
            except Exception: pass
    for state,obj in sorted(rows, key=lambda x:x[1].get('created_at','')): print(f"{obj.get('id')}\t{state}\t{obj.get('title')}")

def issue_close(args):
    p=project_path(args.name); src=p/'issues/open'/f'{args.id}.json'; srcmd=p/'issues/open'/f'{args.id}.md'
    if not src.exists(): raise SystemExit('open issue not found')
    obj=json.loads(src.read_text()); obj['state']='closed'; obj['closed_at']=now(); obj['close_reason']=args.reason or ''
    dst=p/'issues/closed'/src.name; dst.parent.mkdir(parents=True, exist_ok=True); dst.write_text(json.dumps(obj,ensure_ascii=False,indent=2)+'\n') ; src.unlink()
    if srcmd.exists(): shutil.move(str(srcmd), str(p/'issues/closed'/srcmd.name))
    print(args.id)

def attach_report(args):
    p=project_path(args.name); src=Path(args.file).expanduser();
    if not src.exists(): raise SystemExit('file not found')
    dst=p/'reports'/src.name; dst.parent.mkdir(parents=True,exist_ok=True); shutil.copy2(src,dst); print(str(dst))

def report(args):
    p=project_path(args.name); out=p/'reports'/f'project-report-{dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")}.md'
    st=run('git status --short',p).stdout if (p/'.git').exists() else 'no git repo'
    lines=[f'# Project report: {p.name}','',f'Generated: {now()}','','## Git status','','```text',st,'```','','## Issues','']
    for state in ['open','closed']:
        lines.append(f'### {state}')
        for f in sorted((p/'issues'/state).glob('*.json')):
            obj=json.loads(f.read_text()); lines.append(f"- `{obj.get('id')}` {obj.get('title')}")
    out.write_text('\n'.join(lines)+'\n'); print(str(out))
