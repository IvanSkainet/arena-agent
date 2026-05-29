#!/usr/bin/env python3
from __future__ import annotations
import argparse, json, os, shutil, subprocess, textwrap
AURL=os.getenv('AURL') or os.getenv('ARENA_BRIDGE_URL') or ''
ATOK=os.getenv('ATOK') or os.getenv('ARENA_BRIDGE_TOKEN') or ''
def run(c): return subprocess.run(c,shell=True,text=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=20)
def doctor(a):
    checks={'python':shutil.which('python3') or shutil.which('python'),'curl':shutil.which('curl'),'wget':shutil.which('wget'),'requests':False,'AURL':bool(AURL),'ATOK':bool(ATOK)}
    try: import requests; checks['requests']=True
    except Exception: pass
    curl=run(f'curl --curves X25519 -sS --max-time 10 {AURL}/health') if checks['curl'] else None
    print(json.dumps({'ok':True,'checks':checks,'curl_health':curl.stdout[:500] if curl else None,'curl_error':curl.stderr[:500] if curl else None},indent=2))
def gen(a):
    if a.kind=='bash':
        print(textwrap.dedent('''#!/usr/bin/env bash
set -euo pipefail
: "${AURL:?}"; : "${ATOK:?}"
cmd="$1"; timeout="${2:-90}"; max="${3:-30000}"
CMD="$cmd" TIMEOUT="$timeout" MAX="$max" python3 - <<'PY' | curl --curves X25519 -sS --max-time "$((timeout+30))" -H "Authorization: Bearer ${ATOK}" -H 'Content-Type: application/json' --data-binary @- "$AURL/v1/exec"
import json, os
print(json.dumps({'cmd':os.environ['CMD'],'timeout':int(os.environ['TIMEOUT']),'max_output':int(os.environ['MAX'])}))
PY''').strip())
    elif a.kind=='python':
        print(open(os.path.expanduser('~/arena-bridge/bin/ai_client.py')).read())
    elif a.kind=='powershell':
        print('''param([string]$Cmd)\n$body=@{cmd=$Cmd;timeout=90;max_output=30000}|ConvertTo-Json\nInvoke-RestMethod -Uri "$env:AURL/v1/exec" -Method Post -Headers @{Authorization="Bearer $env:ATOK"} -ContentType 'application/json' -Body $body''')
def test(a):
    cmds=[]
    if shutil.which('python3'): cmds.append('python3 ~/arena-bridge/bin/ai_client.py "$AURL" "$ATOK" whoami')
    if shutil.which('curl'): cmds.append('./a whoami 30 4000' if os.path.exists('./a') else f'curl --curves X25519 -sS {AURL}/health')
    out=[]
    for c in cmds:
        p=run(c); out.append({'cmd':c,'exit':p.returncode,'stdout':p.stdout[:1000],'stderr':p.stderr[:1000]})
    print(json.dumps({'ok':all(x['exit']==0 for x in out),'results':out},indent=2))
def main():
    ap=argparse.ArgumentParser(); sub=ap.add_subparsers(dest='cmd',required=True)
    sub.add_parser('doctor').set_defaults(func=doctor)
    s=sub.add_parser('gen'); s.add_argument('kind', choices=['bash','python','powershell']); s.set_defaults(func=gen)
    sub.add_parser('test').set_defaults(func=test)
    a=ap.parse_args(); a.func(a)
if __name__=='__main__': main()
