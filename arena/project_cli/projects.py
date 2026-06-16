"""Project management commands."""
from __future__ import annotations

from arena.project_cli.common import *  # noqa: F401,F403

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
