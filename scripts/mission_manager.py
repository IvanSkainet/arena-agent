#!/usr/bin/env python3
from __future__ import annotations
import argparse, datetime as dt, json, os, re, subprocess, textwrap, uuid
from pathlib import Path


def _fire_mission_hook(event, target, args=None, exit_code=0):
    """Запустить хуки события через hooks_runner. Тихо игнорирует если его нет."""
    try:
        import subprocess as _sp, json as _j, os as _os, pathlib as _pl, sys as _sys
        root = _pl.Path(_os.environ.get("ARENA_AGENT_HOME", str(_pl.Path.home() / "arena-agent")))
        runner = root / "bin" / "hooks_runner.py"
        if not runner.exists():
            return
        _sp.run([_sys.executable, str(runner), "run", event,
                 "--target", target or "",
                 "--args", _j.dumps(args or {}),
                 "--exit", str(exit_code)],
                timeout=70, check=False)
    except Exception:
        pass


def _start_recording(mission_id):
    """Опциональная запись экрана через ffmpeg+sd-exec. ENV: ARENA_REC=1."""
    import os as _os, subprocess as _sp, pathlib as _pl
    if _os.environ.get("ARENA_REC") != "1":
        return None
    root = _pl.Path(_os.environ.get("ARENA_AGENT_HOME", str(_pl.Path.home() / "arena-agent")))
    rec_dir = root / "reports" / "recordings"
    rec_dir.mkdir(parents=True, exist_ok=True)
    out = rec_dir / f"mission-{mission_id}.mp4"
    # ffmpeg через sd-exec — выходим из bridge cgroup, имеем DISPLAY
    sd = root / "bin" / "sd-exec"
    cmd = [str(sd), "--", "ffmpeg", "-y", "-loglevel", "error",
           "-f", "x11grab", "-framerate", "10", "-i",
           _os.environ.get("DISPLAY", ":0"),
           "-vcodec", "libx264", "-preset", "ultrafast",
           "-pix_fmt", "yuv420p", str(out)]
    try:
        proc = _sp.Popen(cmd, stdout=_sp.DEVNULL, stderr=_sp.DEVNULL, start_new_session=True)
        return {"pid": proc.pid, "out": str(out)}
    except Exception:
        return None


def _stop_recording(rec):
    if not rec:
        return
    import os as _os, signal as _sig
    try:
        _os.killpg(_os.getpgid(rec["pid"]), _sig.SIGTERM)
    except Exception:
        try: _os.kill(rec["pid"], _sig.SIGTERM)
        except Exception: pass

ROOT=Path(os.environ.get('ARENA_AGENT_HOME', str(Path.home()/'arena-agent'))).expanduser()
MISSIONS=ROOT/'missions'; TEMPLATES=ROOT/'missions/templates'; REPORTS=ROOT/'reports'; AGENT=ROOT/'bin/agentctl'
def now(): return dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds')
def slug(s): return re.sub(r'[^a-zA-Z0-9._-]+','-',s.strip()).strip('-').lower() or 'mission'
def run_cmd(cmd, timeout=120):
    p=subprocess.run(cmd,shell=True,text=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=timeout)
    return {'cmd':cmd,'exit_code':p.returncode,'stdout':p.stdout[-20000:],'stderr':p.stderr[-12000:],'ts':now()}
TEMPLATES_DATA={
 'tabs-game':{'title':'Play/operate TABS game','goal':'Launch TABS, verify graphics/input, navigate campaign, use screenshots/OCR/web research, play levels with smooth input.','steps':['desktop info','desktop screenshot','window/process detection','input calibration','web research units/strategy','play one level','write report']},
 'browser-real-user':{'title':'Automated browser task','goal':'Use browser like a user: search/read/fill forms/extract results with confirmation gates.','steps':['open URL','screenshot','page dump','readability','interaction plan','extract result','report']},
 'cli-agent-core':{'title':'Core CLI agent self-test','goal':'Verify bridge, task runner, MCP stream, reports, backup, recovery, clients.','steps':['sys status','mcp ping','task list','web probe','browser screenshot','report index','client doctor','backup list']},
 'mcp-integration':{'title':'MCP server integration','goal':'Install/list/test MCP server, call safe tool, document permissions and failures.','steps':['mcp list','stream health','stream init','stream tools','stream call ping','report']},
 'recovery-drill':{'title':'Recovery drill','goal':'Simulate new chat recovery and verify concise prompt/helper/client works.','steps':['recovery print','client doctor','bridge health','sys status','backup list']},
 'code-tdd':{'title':'Code change with TDD','goal':'Use context detector, tests, implementation, review, git commit, report.','steps':['context detect','create branch','write failing test','implement','run tests','self-review','commit']},
 'lan-service':{'title':'Local/LAN service interaction','goal':'Discover and interact with allowed local network service/port.','steps':['define target','scan limited ports','probe HTTP/TLS','document service']},
}
def ensure():
    TEMPLATES.mkdir(parents=True,exist_ok=True); MISSIONS.mkdir(parents=True,exist_ok=True); REPORTS.mkdir(exist_ok=True)
    for k,v in TEMPLATES_DATA.items():
        p=TEMPLATES/f'{k}.json'
        if not p.exists(): p.write_text(json.dumps({'id':k,**v},ensure_ascii=False,indent=2)+'\n')
def load_template(name):
    ensure(); p=TEMPLATES/f'{slug(name)}.json'
    if not p.exists(): raise SystemExit(f'unknown template: {name}')
    return json.loads(p.read_text())
def find_mission(mid):
    ensure(); matches=[p for p in MISSIONS.iterdir() if p.is_dir() and (p.name==mid or p.name.startswith(mid))]
    if not matches: raise SystemExit(f'mission not found: {mid}')
    return sorted(matches)[-1]
def list_cmd(a):
    ensure()
    if a.missions:
        for p in sorted(x for x in MISSIONS.iterdir() if x.is_dir() and not x.name.startswith('.')): print(p.name)
    else:
        for p in sorted(TEMPLATES.glob('*.json')):
            o=json.loads(p.read_text()); print(f"{o['id']}: {o.get('title','')}")
def show_cmd(a): print(json.dumps(load_template(a.name),ensure_ascii=False,indent=2))
def new_cmd(a):
    t=load_template(a.template); mid=dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-'+slug(a.name or t['id'])+'-'+uuid.uuid4().hex[:6]
    d=MISSIONS/mid; (d/'artifacts').mkdir(parents=True); (d/'logs').mkdir(); obj={'id':mid,'template':t['id'],'title':a.name or t['title'],'created_at':now(),'state':'planned','template_data':t,'runs':[]}
    (d/'mission.json').write_text(json.dumps(obj,ensure_ascii=False,indent=2)+'\n')
    lines=['# Mission: '+obj['title'],'',f'ID: `{mid}`','',f'Template: `{t["id"]}`','','## Goal',t['goal'],'','## Steps']+[f'- [ ] {x}' for x in t.get('steps',[])]+['']
    (d/'PLAN.md').write_text('\n'.join(lines)); print(str(d))
def commands_for(template):
    if template=='cli-agent-core': return [f'{AGENT} sys status',f'{AGENT} mcp stream-call ping',f'{AGENT} task list',f'{AGENT} web http https://example.com',f'{AGENT} browser shot https://example.com',f'{AGENT} report index',f'{AGENT} client doctor',f'{AGENT} backup ls']
    if template=='mcp-integration': return [f'{AGENT} mcp list',f'{AGENT} mcp stream-health',f'{AGENT} mcp stream-init',f'{AGENT} mcp stream-tools',f'{AGENT} mcp stream-call ping']
    if template=='recovery-drill': return [f'{AGENT} recovery-print | head -120',f'{AGENT} client doctor',f'curl -sS http://127.0.0.1:8765/health',f'{AGENT} sys status',f'{AGENT} backup ls | tail -10']
    if template=='browser-real-user': return [f'{AGENT} browser shot https://example.com',f'{AGENT} browser dump https://example.com',f'{AGENT} browser read https://example.com']
    if template=='tabs-game': return [f'{AGENT} desktop info',f'{AGENT} desktop shot',f'{AGENT} web http https://totally-accurate-battle-simulator.fandom.com/wiki/Units || true']
    return [f'{AGENT} sys status']
def check_cmd(a): print('\n'.join(commands_for(a.name)))
def status_cmd(a):
    d=find_mission(a.id); obj=json.loads((d/'mission.json').read_text()); print(json.dumps({'ok':True,'path':str(d),'mission':obj},ensure_ascii=False,indent=2))
def run_cmd_mission(a):
    _mission_id = getattr(a, "id", getattr(a, "name", "unknown"))
    _fire_mission_hook("pre_mission", str(_mission_id), {"args": vars(a) if hasattr(a, "__dict__") else {}})
    _rec = _start_recording(str(_mission_id))
    try:
        _rc = _run_cmd_mission_orig(a)
    except Exception:
        _stop_recording(_rec)
        _fire_mission_hook("post_mission", str(_mission_id), {}, 1)
        raise
    _stop_recording(_rec)
    _fire_mission_hook("post_mission", str(_mission_id), {}, _rc or 0)
    return _rc


def _run_cmd_mission_orig(a):
    d=find_mission(a.id); obj=json.loads((d/'mission.json').read_text()); cmds=commands_for(obj['template']); results=[]; obj['state']='running'; obj['started_at']=obj.get('started_at') or now(); (d/'mission.json').write_text(json.dumps(obj,ensure_ascii=False,indent=2)+'\n')
    for i,c in enumerate(cmds,1):
        if a.step and i!=a.step: continue
        r=run_cmd(c,a.timeout); results.append(r); (d/'logs'/f'step-{i:02d}.json').write_text(json.dumps(r,ensure_ascii=False,indent=2)+'\n')
    ok=all(r['exit_code']==0 for r in results); obj['state']='done' if ok else 'failed'; obj['finished_at']=now(); obj.setdefault('runs',[]).append({'ts':now(),'ok':ok,'results':[{'cmd':r['cmd'],'exit_code':r['exit_code']} for r in results]}); (d/'mission.json').write_text(json.dumps(obj,ensure_ascii=False,indent=2)+'\n')
    report_cmd(argparse.Namespace(id=d.name)); print(json.dumps({'ok':ok,'mission':d.name,'state':obj['state'],'steps':len(results)},ensure_ascii=False,indent=2))
def report_cmd(a):
    d=find_mission(a.id); obj=json.loads((d/'mission.json').read_text()); out=d/'REPORT.md'; lines=[f'# Mission report: {obj["title"]}','',f'ID: `{obj["id"]}`',f'State: `{obj.get("state")}`',f'Generated: {now()}','','## Step logs']
    for f in sorted((d/'logs').glob('step-*.json')):
        r=json.loads(f.read_text()); lines += [f'### {f.stem}: `{r["cmd"]}`',f'Exit: `{r["exit_code"]}`','','```text',(r.get('stdout','')+r.get('stderr',''))[:6000],'```','']
    out.write_text('\n'.join(lines)); print(str(out))
def stress_cmd(a):
    tmp=MISSIONS/'stress-current'; tmp.mkdir(parents=True,exist_ok=True); mid=newest='stress-current'
    obj={'id':mid,'template':'cli-agent-core','title':'Core stress','state':'planned','created_at':now(),'runs':[]}; (tmp/'mission.json').write_text(json.dumps(obj,ensure_ascii=False,indent=2)); (tmp/'logs').mkdir(exist_ok=True); run_cmd_mission(argparse.Namespace(id=mid,step=None,timeout=180))
def roadmap_cmd(a):
    out=ROOT/'ROADMAP.md'; out.write_text(textwrap.dedent('''# Arena Agent Roadmap

## Core
- Bridge as control plane, heavy tasks via transient services.
- Short commands via `agentctl commands` and `./a` helper.
- Recovery prompt as bootloader, not history dump.

## Scenarios
- TABS/game operation.
- Browser real-user automation.
- MCP integration.
- Recovery drill.
- Code TDD.

## Next
- Mission runner artifacts and dashboard.
- Client/UPS test-all.
- BrowserAct adapter.
- Real MCP server practical tests.
''').strip()+'\n'); print(out)
def main():
    ap=argparse.ArgumentParser(); sub=ap.add_subparsers(dest='cmd',required=True)
    s=sub.add_parser('list'); s.add_argument('--missions',action='store_true'); s.set_defaults(func=list_cmd)
    s=sub.add_parser('show'); s.add_argument('name'); s.set_defaults(func=show_cmd)
    s=sub.add_parser('new'); s.add_argument('template'); s.add_argument('--name'); s.set_defaults(func=new_cmd)
    s=sub.add_parser('check'); s.add_argument('name'); s.set_defaults(func=check_cmd)
    s=sub.add_parser('status'); s.add_argument('id'); s.set_defaults(func=status_cmd)
    s=sub.add_parser('run'); s.add_argument('id'); s.add_argument('--step',type=int); s.add_argument('--timeout',type=int,default=180); s.set_defaults(func=run_cmd_mission)
    s=sub.add_parser('report'); s.add_argument('id'); s.set_defaults(func=report_cmd)
    s=sub.add_parser('stress'); s.set_defaults(func=stress_cmd)
    s=sub.add_parser('roadmap'); s.set_defaults(func=roadmap_cmd)
    a=ap.parse_args(); a.func(a)
if __name__=='__main__': main()
