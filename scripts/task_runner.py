#!/usr/bin/env python3
from __future__ import annotations
import argparse, datetime as dt, json, os, shutil, subprocess, sys, time, uuid
from pathlib import Path

ROOT = Path(os.environ.get('ARENA_AGENT_HOME', str(Path.home() / 'arena-agent'))).expanduser()
QUEUE = ROOT / 'queue'
INBOX = QUEUE / 'inbox'
RUNNING = QUEUE / 'running'
DONE = QUEUE / 'done'
FAILED = QUEUE / 'failed'
LOGS = ROOT / 'logs'


def now(): return dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds')

def ensure():
    for p in [INBOX, RUNNING, DONE, FAILED, LOGS]: p.mkdir(parents=True, exist_ok=True)
    os.chmod(QUEUE, 0o700)

def read_json(p: Path):
    with p.open('r', encoding='utf-8') as f: return json.load(f)

def write_json(p: Path, obj):
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + '.tmp')
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    tmp.replace(p)
    try: os.chmod(p, 0o600)
    except Exception: pass

def submit(args):
    ensure()
    tid = args.id or dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '-' + uuid.uuid4().hex[:8]
    task = {
        'id': tid,
        'created_at': now(),
        'cmd': args.cmd,
        'cwd': args.cwd,
        'timeout': args.timeout,
        'max_output': args.max_output,
        'env': {},
        'notes': args.notes or '',
    }
    p = INBOX / f'{tid}.json'
    write_json(p, task)
    print(str(p))

def list_tasks(args):
    ensure()
    for name, d in [('inbox', INBOX), ('running', RUNNING), ('done', DONE), ('failed', FAILED)]:
        rows = sorted(d.glob('*.json'))[-args.limit:]
        print(f'## {name} ({len(rows)})')
        for p in rows:
            try:
                obj = read_json(p)
                print(f"{p.stem}\t{obj.get('created_at') or obj.get('started_at') or ''}\t{obj.get('exit_code','')}\t{str(obj.get('cmd',''))[:100]}")
            except Exception as e:
                print(f'{p.name}\tERR {e}')

def run_one_file(p: Path):
    ensure()
    task = read_json(p)
    tid = task.get('id') or p.stem
    rp = RUNNING / p.name
    try:
        p.rename(rp)
    except FileNotFoundError:
        return False
    task['started_at'] = now()
    task['state'] = 'running'
    write_json(rp, task)
    cwd = Path(task.get('cwd') or str(Path.home())).expanduser()
    timeout = int(task.get('timeout') or 3600)
    max_output = int(task.get('max_output') or 2_000_000)
    env = os.environ.copy()
    if isinstance(task.get('env'), dict):
        env.update({str(k): str(v) for k,v in task['env'].items()})
    t0 = time.time()
    try:
        proc = subprocess.run(task['cmd'], shell=True, cwd=str(cwd), env=env, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout)
        duration = round(time.time() - t0, 3)
        out, err = proc.stdout, proc.stderr
        truncated = False
        if len(out.encode('utf-8','replace')) > max_output:
            out = out.encode('utf-8','replace')[:max_output].decode('utf-8','replace'); truncated = True
        if len(err.encode('utf-8','replace')) > max_output:
            err = err.encode('utf-8','replace')[:max_output].decode('utf-8','replace'); truncated = True
        task.update({'finished_at': now(), 'duration_sec': duration, 'exit_code': proc.returncode, 'stdout': out, 'stderr': err, 'truncated': truncated, 'state': 'done' if proc.returncode == 0 else 'failed'})
        dest = (DONE if proc.returncode == 0 else FAILED) / p.name
    except subprocess.TimeoutExpired as e:
        task.update({'finished_at': now(), 'duration_sec': round(time.time()-t0,3), 'exit_code': 124, 'stdout': e.stdout if isinstance(e.stdout,str) else '', 'stderr': e.stderr if isinstance(e.stderr,str) else '', 'state': 'failed', 'error': f'timeout after {timeout}s'})
        dest = FAILED / p.name
    except Exception as e:
        task.update({'finished_at': now(), 'duration_sec': round(time.time()-t0,3), 'exit_code': 125, 'stdout': '', 'stderr': repr(e), 'state': 'failed', 'error': repr(e)})
        dest = FAILED / p.name
    write_json(dest, task)
    try: rp.unlink()
    except FileNotFoundError: pass
    print(f"{tid}: {task['state']} exit={task.get('exit_code')} duration={task.get('duration_sec')}")
    return True

def run_once(args):
    ensure()
    count = 0
    for p in sorted(INBOX.glob('*.json'))[:args.max]:
        if run_one_file(p): count += 1
    if count == 0 and not getattr(args, 'quiet', False): print('no tasks')

def watch(args):
    ensure()
    print(f'watching {INBOX}; interval={args.interval}s')
    while True:
        run_once(argparse.Namespace(max=args.max, quiet=True))
        time.sleep(args.interval)

def show(args):
    ensure()
    for d in [INBOX, RUNNING, DONE, FAILED]:
        p = d / f'{args.id}.json'
        if p.exists():
            print(p.read_text(encoding='utf-8'))
            return
    print(f'not found: {args.id}', file=sys.stderr); raise SystemExit(1)

def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest='cmd', required=True)
    p=sub.add_parser('submit'); p.add_argument('cmd'); p.add_argument('--id'); p.add_argument('--cwd'); p.add_argument('--timeout', type=int, default=3600); p.add_argument('--max-output', type=int, default=2_000_000); p.add_argument('--notes'); p.set_defaults(func=submit)
    p=sub.add_parser('list'); p.add_argument('--limit', type=int, default=20); p.set_defaults(func=list_tasks)
    p=sub.add_parser('run-once'); p.add_argument('--max', type=int, default=1); p.set_defaults(func=run_once)
    p=sub.add_parser('watch'); p.add_argument('--interval', type=float, default=5); p.add_argument('--max', type=int, default=1); p.set_defaults(func=watch)
    p=sub.add_parser('show'); p.add_argument('id'); p.set_defaults(func=show)
    args=ap.parse_args(); args.func(args)
if __name__ == '__main__': main()
