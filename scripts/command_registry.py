#!/usr/bin/env python3
from __future__ import annotations
import argparse, json
GROUPS={
 'sys':[('status','health/services/funnel/memory'),('doctor','diagnostics'),('svc','systemd status'),('funnel','tailscale funnel')],
 'mcp':[('stream-health','health 8767'),('stream-init','initialize'),('stream-tools','list stream tools'),('stream-call ping','call test tool'),('list','stdio config'),('tools NAME','stdio tools')],
 'browser':[('shot URL','screenshot'),('fp URL','fingerprint'),('dump URL','html/text/json'),('read URL','readability')],
 'web':[('http URL','http probe'),('dns DOMAIN','dns records'),('tls HOST','tls cert'),('head URL','headers'),('robots URL','robots'),('sitemap URL','sitemap')],
 'mission':[('list','templates'),('show NAME','template'),('new TEMPLATE --name NAME','create mission'),('check TEMPLATE','capability checklist'),('stress','core stress test'),('roadmap','write roadmap')],
 'proj':[('ls','projects'),('new NAME --git','new git project'),('use NAME','set current'),('status','status'),('commit -m MSG','commit')],
 'task':[('list','queue'),('sub CMD','submit'),('last','last'),('clean --days N','archive old')],
 'mem':[('set KEY VALUE --tags a b','remember'),('get QUERY','recall')],
 'report':[('ls','recent reports'),('idx','index'),('latest PATTERN','latest matching')],
 'backup':[('run','create backup'),('ls','list backups')],
 'desktop':[('info','desktop info'),('shot','screenshot'),('click/type/key','input')],
}
def main():
    ap=argparse.ArgumentParser(); ap.add_argument('group', nargs='?'); ap.add_argument('--json', action='store_true'); a=ap.parse_args()
    data={k:[{'cmd':c,'desc':d} for c,d in v] for k,v in GROUPS.items()}
    if a.group: data={a.group:data.get(a.group,[])}
    if a.json: print(json.dumps(data,indent=2)); return
    for g,items in data.items():
        print(f'[{g}]')
        for x in items: print(f'  agentctl {g} {x["cmd"]:<28} # {x["desc"]}')
if __name__=='__main__': main()
