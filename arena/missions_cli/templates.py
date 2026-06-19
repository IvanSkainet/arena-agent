"""Mission template helpers."""
from __future__ import annotations

from arena.missions_cli.common import *  # noqa: F401,F403

TEMPLATES_DATA={
 'tabs-game':{'title':'Play/operate TABS game','goal':'Launch TABS, verify graphics/input, navigate campaign, use screenshots/OCR/web research, play levels with smooth input.','steps':['desktop info','desktop screenshot','window/process detection','input calibration','web research units/strategy','play one level','write report']},
 'browser-real-user':{'title':'Automated browser task','goal':'Use browser like a user: search/read/fill forms/extract results with confirmation gates.','steps':['open URL','screenshot','page dump','readability','interaction plan','extract result','report']},
 'cli-agent-core':{'title':'Core CLI agent self-test','goal':'Verify bridge, task runner, MCP stream, reports, recovery, and clients.','steps':['sys status','mcp ping','task list','web probe','browser screenshot','report index','client doctor','audit stats']},
 'mcp-integration':{'title':'MCP server integration','goal':'Install/list/test MCP server, call safe tool, document permissions and failures.','steps':['mcp list','stream health','stream init','stream tools','stream call ping','report']},
 'recovery-drill':{'title':'Recovery drill','goal':'Simulate new chat recovery and verify concise prompt/helper/client works.','steps':['recovery print','client doctor','bridge health','sys status','audit stats']},
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

def commands_for(template):
    if template=='cli-agent-core': return [f'{AGENT} sys status',f'{AGENT} mcp stream-call ping',f'{AGENT} task list',f'{AGENT} web http https://example.com',f'{AGENT} browser shot https://example.com',f'{AGENT} report index',f'{AGENT} client doctor',f'{AGENT} audit stats']
    if template=='mcp-integration': return [f'{AGENT} mcp list',f'{AGENT} mcp stream-health',f'{AGENT} mcp stream-init',f'{AGENT} mcp stream-tools',f'{AGENT} mcp stream-call ping']
    if template=='recovery-drill': return [f'{AGENT} recovery-print | head -120',f'{AGENT} client doctor',f'curl -sS http://127.0.0.1:8765/health',f'{AGENT} sys status',f'{AGENT} audit stats | tail -10']
    if template=='browser-real-user': return [f'{AGENT} browser shot https://example.com',f'{AGENT} browser dump https://example.com',f'{AGENT} browser read https://example.com']
    if template=='tabs-game': return [f'{AGENT} desktop info',f'{AGENT} desktop shot',f'{AGENT} web http https://totally-accurate-battle-simulator.fandom.com/wiki/Units || true']
    return [f'{AGENT} sys status']
