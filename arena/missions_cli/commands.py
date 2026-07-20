"""Mission manager commands."""
from __future__ import annotations

from arena.missions_cli.templates import *  # noqa: F401,F403
from arena.missions_cli.common import _fire_mission_hook, _start_recording, _stop_recording  # noqa: F401

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
    d=find_mission(a.id); obj=json.loads((d/'mission.json').read_text())
    # v4.55.0: scenario-typed missions run through the in-process
    # scenarios runtime because their steps are Arena TOOL CALLS,
    # not shell commands. mission_manager is a subprocess and
    # has no access to the bridge's tool dispatcher, so we exit
    # with a friendly redirect instead of trying to execute the
    # steps as shell.
    if obj.get('template') == 'scenario':
        msg = (
            f"mission {d.name!r} is a scenario (template=scenario). "
            f"Run it via the bridge scenario.run tool, e.g.:\n"
            f"  curl -sS -X POST http://127.0.0.1:8765/v1/extension/execute \\\n"
            f"    -H 'Authorization: Bearer <token>' -d '{{\"payload\":{{\"bridge\":\"arena\",\"version\":1,\"calls\":"
            f"[{{\"id\":\"c1\",\"tool\":\"scenario.run\",\"arguments\":{{\"name\":\"{obj.get('template_data',{}).get('name', d.name)}\"}}}}]}},\"mode\":{{\"approve\":true}}}}'"
        )
        print(json.dumps({'ok':False,'mission':d.name,'state':obj.get('state','planned'),'error':'scenario mission — use scenario.run','hint':msg},ensure_ascii=False,indent=2))
        raise SystemExit(2)
    cmds=commands_for(obj['template']); results=[]; obj['state']='running'; obj['started_at']=obj.get('started_at') or now(); (d/'mission.json').write_text(json.dumps(obj,ensure_ascii=False,indent=2)+'\n')
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
