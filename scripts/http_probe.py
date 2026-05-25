#!/usr/bin/env python3
from __future__ import annotations
import argparse, json, time
import httpx

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('url')
    ap.add_argument('--method', default='GET')
    ap.add_argument('--timeout', type=float, default=30)
    args=ap.parse_args()
    t=time.time()
    with httpx.Client(http2=True, follow_redirects=True, timeout=args.timeout, headers={'user-agent':'arena-agent-http-probe/0.1'}) as c:
        r=c.request(args.method, args.url)
    body=r.text[:10000]
    print(json.dumps({'ok': True, 'url': str(r.url), 'status_code': r.status_code, 'http_version': r.http_version, 'elapsed_sec': round(time.time()-t,3), 'headers': dict(r.headers), 'body_preview': body}, ensure_ascii=False, indent=2))
if __name__ == '__main__': main()
