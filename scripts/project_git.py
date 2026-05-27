#!/usr/bin/env python3
from __future__ import annotations
import argparse, datetime as dt, json, os, shutil, subprocess, sys, uuid
from pathlib import Path


def _show_agents_md(proj_dir):
    """Если в проекте есть AGENTS.md / CLAUDE.md / .agents.md — показать первые 40 строк."""
    import pathlib as _pl
    for name in ("AGENTS.md", "agents.md", "CLAUDE.md", ".agents.md"):
        p = _pl.Path(proj_dir) / name
        if p.exists():
            try:
                txt = p.read_text(errors="replace")
                head = "\n".join(txt.splitlines()[:40])
                print()
                print(f"=== {name} ({len(txt)} bytes) ===")
                print(head)
                if len(txt.splitlines()) > 40:
                    print(f"... ({len(txt.splitlines())} lines total)")
            except Exception:
                pass
            return True
    return False

ROOT=Path(os.environ.get('ARENA_AGENT_HOME', str(Path.home()/'arena-bridge'))).expanduser()
PROJECTS=ROOT/'projects'; CURRENT=PROJECTS/'.current'
def now(): return dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds')
def safe(name):
    s=''.join(c if c.isalnum() or c in '-_.' else '-' for c in name.strip())
    if not s or s.startswith('.'): raise SystemExit('bad project name')
    return s
def project_path(name=None):
    if not name:
        if not CURRENT.exists(): raise SystemExit('no current project; run project-use NAME')
        name=CURRENT.read_text().strip()
    p=PROJECTS/safe(name)
    if not p.exists(): raise SystemExit(f'project not found: {name}')
    return p
def run(cmd, cwd, check=False):
    p=subprocess.run(cmd, shell=True, cwd=str(cwd), text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if check and p.returncode!=0:
        sys.stdout.write(p.stdout); sys.stderr.write(p.stderr); raise SystemExit(p.returncode)
    return p
def ensure_git_identity(p):
    if run('git config user.email', p).returncode != 0 or not run('git config user.email', p).stdout.strip():
        run('git config user.email "arena-bridge@local"', p)
    if run('git config user.name', p).returncode != 0 or not run('git config user.name', p).stdout.strip():
        run('git config user.name "Arena Agent"', p)
def new_project(args):
    name=safe(args.name); p=PROJECTS/name; p.mkdir(parents=True, exist_ok=True)
    for d in ['data','src','reports','notes','tmp','issues/open','issues/closed','merge-requests/open','merge-requests/closed']:(p/d).mkdir(parents=True, exist_ok=True)
    (p/'.gitignore').write_text('.env\n.env.*\nsecrets/\ntmp/\n*.log\n.DS_Store\nnode_modules/\n.venv/\n', encoding='utf-8') if not (p/'.gitignore').exists() else None
    if not (p/'README.md').exists(): (p/'README.md').write_text(f'# {name}\n\nCreated: {now()}\n\n{args.description or ""}\n', encoding='utf-8')
    meta=p/'project.json'
    if not meta.exists(): meta.write_text(json.dumps({'name':name,'created_at':now(),'description':args.description or ''}, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    if args.git: git_init(argparse.Namespace(name=name, message='Initial project scaffold'))
    print(str(p))
def use(args):
    p=project_path(args.name); CURRENT.parent.mkdir(parents=True, exist_ok=True); CURRENT.write_text(p.name); print(p.name)
def current(args): print(CURRENT.read_text().strip() if CURRENT.exists() else '')
def list_projects(args):
    PROJECTS.mkdir(parents=True, exist_ok=True)
    cur=CURRENT.read_text().strip() if CURRENT.exists() else None
    for p in sorted(x for x in PROJECTS.iterdir() if x.is_dir() and not x.name.startswith('.')): print(('* ' if p.name==cur else '  ')+p.name)
def git_init(args):
    p=project_path(args.name)
    if not (p/'.git').exists(): run('git init', p, check=True)
    ensure_git_identity(p)
    run('git add -A', p, check=True)
    msg=getattr(args,'message','Initial commit') or 'Initial commit'
    c=run(f'git commit -m {json.dumps(msg)}', p)
    if c.returncode!=0 and 'nothing to commit' not in (c.stdout+c.stderr).lower(): sys.stdout.write(c.stdout); sys.stderr.write(c.stderr); raise SystemExit(c.returncode)
    print(c.stdout+c.stderr)
def status(args):
    p=project_path(args.name); out={'ok':True,'project':p.name,'path':str(p),'git':(p/'.git').exists()}
    if out['git']:
        out['branch']=run('git branch --show-current',p).stdout.strip(); out['status']=run('git status --short',p).stdout.splitlines(); out['last_commit']=run('git log -1 --oneline',p).stdout.strip()
    files=[]
    for x in sorted(p.rglob('*')):
        if '.git' in x.parts: continue
        if x.is_file(): files.append({'path':str(x.relative_to(p)),'size':x.stat().st_size})
    out['files']=files[:500]
    print(json.dumps(out, ensure_ascii=False, indent=2))
def commit(args):
    p=project_path(args.name); 
    if not (p/'.git').exists(): git_init(argparse.Namespace(name=p.name,message='Initial commit'))
    ensure_git_identity(p); run('git add -A',p,check=True); c=run(f'git commit -m {json.dumps(args.message)}',p)
    if c.returncode!=0 and 'nothing to commit' not in (c.stdout+c.stderr).lower(): sys.stdout.write(c.stdout); sys.stderr.write(c.stderr); raise SystemExit(c.returncode)
    print(c.stdout+c.stderr)
def log(args): print(run(f'git log --oneline --decorate -n {args.limit}', project_path(args.name)).stdout)
def branch(args):
    p=project_path(args.name)
    if args.create:
        print(run(f'git checkout -b {shq(args.create)}',p).stdout+run(f'git branch --show-current',p).stdout)
    elif args.checkout:
        print(run(f'git checkout {shq(args.checkout)}',p,check=True).stdout)
    else: print(run('git branch -vv',p).stdout)
def shq(s): return "'"+s.replace("'","'\\''")+"'"
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
            except: pass
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
def main():
    ap=argparse.ArgumentParser(); sub=ap.add_subparsers(dest='cmd', required=True)
    s=sub.add_parser('new'); s.add_argument('name'); s.add_argument('--description'); s.add_argument('--git', action='store_true'); s.set_defaults(func=new_project)
    s=sub.add_parser('use'); s.add_argument('name'); s.set_defaults(func=use)
    s=sub.add_parser('current'); s.set_defaults(func=current)
    s=sub.add_parser('list'); s.set_defaults(func=list_projects)
    s=sub.add_parser('git-init'); s.add_argument('name', nargs='?'); s.add_argument('-m','--message', default='Initial commit'); s.set_defaults(func=git_init)
    s=sub.add_parser('status'); s.add_argument('name', nargs='?'); s.set_defaults(func=status)
    s=sub.add_parser('commit'); s.add_argument('name', nargs='?'); s.add_argument('-m','--message', required=True); s.set_defaults(func=commit)
    s=sub.add_parser('log'); s.add_argument('name', nargs='?'); s.add_argument('-n','--limit', type=int, default=20); s.set_defaults(func=log)
    s=sub.add_parser('branch'); s.add_argument('name', nargs='?'); s.add_argument('--create'); s.add_argument('--checkout'); s.set_defaults(func=branch)
    s=sub.add_parser('issue-new'); s.add_argument('name', nargs='?'); s.add_argument('title'); s.add_argument('--body'); s.set_defaults(func=issue_new)
    s=sub.add_parser('issues'); s.add_argument('name', nargs='?'); s.set_defaults(func=issue_list)
    s=sub.add_parser('issue-close'); s.add_argument('name', nargs='?'); s.add_argument('id'); s.add_argument('--reason'); s.set_defaults(func=issue_close)
    s=sub.add_parser('attach-report'); s.add_argument('name', nargs='?'); s.add_argument('file'); s.set_defaults(func=attach_report)
    s=sub.add_parser('report'); s.add_argument('name', nargs='?'); s.set_defaults(func=report)
    a=ap.parse_args(); a.func(a)
if __name__=='__main__': main()


def agents_md_command(args):
    """CLI: project_git.py agents [init|show] — управление AGENTS.md в текущем проекте."""
    import os as _os, pathlib as _pl, shutil as _sh
    state = _pl.Path.home() / ".arena-bridge" / "current_project"
    cur = None
    if state.exists(): cur = state.read_text().strip()
    if not cur:
        # пробуем найти через .arena-bridge в текущем
        cur = _os.environ.get("ARENA_CURRENT_PROJECT", "")
    if not cur:
        # последний из projects/
        proj_root = _pl.Path.home() / "arena-bridge" / "projects"
        if proj_root.exists():
            dirs = sorted([d for d in proj_root.iterdir() if d.is_dir()],
                          key=lambda p: p.stat().st_mtime, reverse=True)
            if dirs: cur = str(dirs[0])
    if not cur:
        print("No current project. Use `agentctl proj use NAME` first.")
        return 1
    proj_dir = _pl.Path(cur)
    if not proj_dir.is_absolute():
        proj_dir = _pl.Path.home() / "arena-bridge" / "projects" / proj_dir
    sub = args[0] if args else "show"
    target = proj_dir / "AGENTS.md"
    if sub == "init":
        tmpl = _pl.Path.home() / "arena-bridge" / "docs" / "AGENTS.md.template"
        if not tmpl.exists():
            print("template missing:", tmpl); return 1
        if target.exists():
            print("already exists:", target); return 1
        text = tmpl.read_text().replace("{name}", proj_dir.name)
        target.write_text(text)
        print("created:", target)
        return 0
    # show
    if not target.exists():
        print(f"no AGENTS.md at {target}\nrun: agentctl proj agents init")
        return 1
    print(target.read_text())
    return 0

# Hook dispatcher if main exists
import sys as _sys
if __name__ == "__main__" and len(_sys.argv) > 1 and _sys.argv[1] == "agents":
    _sys.exit(agents_md_command(_sys.argv[2:]))
