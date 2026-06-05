#!/usr/bin/env python3
"""Fallback client: urllib -> requests -> curl(--curves X25519) -> wget.
Usage: fallback_client.py [URL] [TOKEN] <cmd...>
Env: AURL/ATOK or ARENA_BRIDGE_URL/ARENA_BRIDGE_TOKEN.
"""
from __future__ import annotations
import json, os, subprocess, sys, urllib.request

def payload(cmd): return json.dumps({'cmd':cmd,'timeout':90,'max_output':30000}, ensure_ascii=False).encode()
def parse(b):
    r=json.loads(b.decode() if isinstance(b,bytes) else b)
    return (r.get('stdout','') or '') + (r.get('stderr','') or '') if r.get('ok', True) else 'ERR: '+str(r.get('error') or r)
def ureq(url,tok,cmd):
    req=urllib.request.Request(url.rstrip()+'/v1/exec',data=payload(cmd),headers={'Authorization':'Bearer '+tok,'Content-Type':'application/json'},method='POST')
    with urllib.request.urlopen(req,timeout=120) as r: return parse(r.read())
def reqs(url,tok,cmd):
    import requests
    r=requests.post(url.rstrip()+'/v1/exec',data=payload(cmd),headers={'Authorization':'Bearer '+tok,'Content-Type':'application/json'},timeout=120)
    return parse(r.text)
def curl(url,tok,cmd):
    p=subprocess.run(['curl','--curves','X25519','-sS','--max-time','120','-H','Authorization: Bearer '+tok,'-H','Content-Type: application/json','--data-binary','@-',url.rstrip()+'/v1/exec'],input=payload(cmd),stdout=subprocess.PIPE,stderr=subprocess.PIPE)
    if p.returncode: raise RuntimeError(p.stderr.decode())
    return parse(p.stdout)
def wget(url,tok,cmd):
    p=subprocess.run(['wget','-qO-','--header','Authorization: Bearer '+tok,'--header','Content-Type: application/json','--post-data',payload(cmd).decode(),url.rstrip()+'/v1/exec'],stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=120)
    if p.returncode: raise RuntimeError(p.stderr.decode())
    return parse(p.stdout)
def main():
    a=sys.argv[1:]; url=os.getenv('AURL') or os.getenv('ARENA_BRIDGE_URL'); tok=os.getenv('ATOK') or os.getenv('ARENA_BRIDGE_TOKEN')
    if len(a)>=3 and a[0].startswith('http'): url,tok=a[0],a[1]; a=a[2:]
    if not url or not tok or not a: print(__doc__.strip()); return 2
    cmd=' '.join(a)
    errs=[]
    for name,fn in [('urllib',ureq),('requests',reqs),('curl',curl),('wget',wget)]:
        try: print(f'[{name}] '+fn(url,tok,cmd), end=''); return 0
        except Exception as e: errs.append(f'{name}: {e}')
    print('[ERROR] all fallback methods failed\n'+'\n'.join(errs), file=sys.stderr); return 1
if __name__=='__main__': raise SystemExit(main())
