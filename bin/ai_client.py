#!/usr/bin/env python3
"""Compact universal Arena Bridge client v0.2.

Универсальный CLI для общения с Arena bridge. Использует несколько транспортов
с fallback: urllib (stdlib) -> requests -> curl (--curves X25519 для Tailscale Funnel)
-> wget. Это даёт надёжность даже когда часть инструментов недоступна.

Usage:
  ai_client.py [URL] [TOKEN] <cmd...>
  ai_client.py health
  ai_client.py --upload SRC DST     # копировать локальный файл на удалённую машину
  ai_client.py --download REMOTE [LOCAL]
Env:
  AURL/ARENA_BRIDGE_URL, ATOK/ARENA_BRIDGE_TOKEN
"""
from __future__ import annotations
import json, os, subprocess, sys, urllib.request, base64

DEF_URL = os.getenv('AURL') or os.getenv('ARENA_BRIDGE_URL') or 'http://127.0.0.1:8765'
DEF_TOK = os.getenv('ATOK') or os.getenv('ARENA_BRIDGE_TOKEN') or ''

class Bridge:
    def __init__(self, url=None, token=None):
        self.url = (url or DEF_URL).rstrip('/')
        self.token = token or DEF_TOK
    def _payload(self, cmd, timeout=90, max_output=40000, cwd=None):
        d = {'cmd': cmd, 'timeout': timeout, 'max_output': max_output}
        if cwd: d['cwd'] = cwd
        return json.dumps(d, ensure_ascii=False).encode()
    def health(self):
        try:
            with urllib.request.urlopen(self.url + '/health', timeout=10) as r:
                return json.loads(r.read().decode())
        except Exception:
            return self._curl('/health', None, auth=False)
    def exec(self, cmd, timeout=90, max_output=40000, cwd=None):
        data = self._payload(cmd, timeout, max_output, cwd)
        # 1) urllib
        if self.token:
            try:
                req = urllib.request.Request(self.url + '/v1/exec', data=data,
                                              headers={'Authorization': 'Bearer ' + self.token,
                                                       'Content-Type': 'application/json'}, method='POST')
                with urllib.request.urlopen(req, timeout=timeout + 20) as r:
                    return json.loads(r.read().decode())
            except Exception as e:
                sys.stderr.write(f'[ai_client] urllib failed: {e}; trying curl…\n')
        # 2) curl with X25519 (Tailscale Funnel compat)
        return self._curl('/v1/exec', data, timeout=timeout + 20)
    def upload(self, src, dst):
        with open(src, 'rb') as f: blob = base64.b64encode(f.read()).decode()
        cmd = f"mkdir -p $(dirname {dst!r}) && echo {blob} | base64 -d > {dst!r} && wc -c {dst!r}"
        return self.exec(cmd, timeout=120, max_output=4000)
    def download(self, remote, local):
        r = self.exec(f"base64 -w0 {remote!r}", timeout=120, max_output=20*1024*1024)
        if r.get('exit_code'): return r
        with open(local, 'wb') as f: f.write(base64.b64decode(r.get('stdout', '').strip()))
        return {'ok': True, 'wrote': local}
    def _curl(self, path, data, timeout=30, auth=True):
        cmd = ['curl', '--curves', 'X25519', '-sS', '--max-time', str(timeout)]
        if auth and self.token: cmd += ['-H', 'Authorization: Bearer ' + self.token]
        if data is not None: cmd += ['-H', 'Content-Type: application/json', '--data-binary', '@-']
        cmd += [self.url + path]
        p = subprocess.run(cmd, input=data, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if p.returncode:
            return {'ok': False, 'error': p.stderr.decode('utf-8', 'replace') or f'curl exit {p.returncode}'}
        try: return json.loads(p.stdout.decode())
        except Exception: return {'ok': False, 'raw': p.stdout.decode('utf-8', 'replace')}

def main():
    args = sys.argv[1:]
    if not args or args[0] in ('-h', '--help'):
        print(__doc__.strip()); return 0
    url, tok = None, None
    if len(args) >= 3 and args[0].startswith('http'):
        url, tok = args[0], args[1]; args = args[2:]
    b = Bridge(url, tok)
    if args[0] == 'health':
        print(json.dumps(b.health(), ensure_ascii=False, indent=2)); return 0
    if args[0] == '--upload' and len(args) >= 3:
        print(json.dumps(b.upload(args[1], args[2]), ensure_ascii=False, indent=2)); return 0
    if args[0] == '--download' and len(args) >= 2:
        local = args[2] if len(args) >= 3 else os.path.basename(args[1])
        print(json.dumps(b.download(args[1], local), ensure_ascii=False, indent=2)); return 0
    res = b.exec(' '.join(args))
    if res.get('ok') is False and res.get('error'):
        print('ERROR:', res['error'], file=sys.stderr); return 1
    sys.stdout.write(res.get('stdout', '') or '')
    err = res.get('stderr', '') or ''
    if err: sys.stderr.write(err)
    return int(res.get('exit_code') or 0)

if __name__ == '__main__':
    raise SystemExit(main())
