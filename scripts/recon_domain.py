#!/usr/bin/env python3
from __future__ import annotations
import argparse, json, socket, ssl, subprocess, time
from datetime import datetime, timezone
import dns.resolver, httpx
def dns_records(domain, rtype):
    try: return [r.to_text() for r in dns.resolver.resolve(domain, rtype, lifetime=5)]
    except Exception as e: return {'error': repr(e)}
def tls_info(host, port=443):
    try:
        ctx=ssl.create_default_context()
        with socket.create_connection((host, port), timeout=8) as sock:
            with ctx.wrap_socket(sock, server_hostname=host) as s:
                cert=s.getpeercert()
                return {'version': s.version(), 'cipher': s.cipher(), 'subject': cert.get('subject'), 'issuer': cert.get('issuer'), 'notBefore': cert.get('notBefore'), 'notAfter': cert.get('notAfter')}
    except Exception as e: return {'error': repr(e)}
def http_probe(url):
    try:
        t=time.time()
        with httpx.Client(http2=True, follow_redirects=True, timeout=12, headers={'user-agent':'arena-agent-recon/0.1'}) as c: r=c.get(url)
        return {'status_code': r.status_code, 'url': str(r.url), 'http_version': r.http_version, 'elapsed_sec': round(time.time()-t,3), 'server': r.headers.get('server'), 'content_type': r.headers.get('content-type'), 'body_preview': r.text[:1000]}
    except Exception as e: return {'error': repr(e)}
def main():
    ap=argparse.ArgumentParser(); ap.add_argument('domain'); ap.add_argument('--whois', action='store_true'); args=ap.parse_args()
    d=args.domain.strip().rstrip('/'); out={'ok': True, 'domain': d, 'ts': datetime.now(timezone.utc).isoformat(timespec='seconds'), 'dns': {}, 'http': {}, 'tls': {}}
    for rt in ['A','AAAA','MX','NS','TXT','CAA','SOA']: out['dns'][rt]=dns_records(d, rt)
    out['tls']['443']=tls_info(d,443); out['http']['http']=http_probe('http://'+d); out['http']['https']=http_probe('https://'+d)
    if args.whois:
        try:
            p=subprocess.run(['whois', d], text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=15)
            out['whois']={'exit_code': p.returncode, 'stdout_preview': p.stdout[:20000], 'stderr_preview': p.stderr[:4000]}
        except Exception as e: out['whois']={'error': repr(e)}
    print(json.dumps(out, ensure_ascii=False, indent=2))
if __name__=='__main__': main()
