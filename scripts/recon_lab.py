#!/usr/bin/env python3
from __future__ import annotations
import argparse, json, re, socket, ssl, time
from urllib.parse import urljoin, urlparse
import dns.resolver, httpx

def j(x): print(json.dumps(x, ensure_ascii=False, indent=2))
def dns_lookup(domain, types):
    out={}
    for rt in types:
        try: out[rt]=[r.to_text() for r in dns.resolver.resolve(domain, rt, lifetime=6)]
        except Exception as e: out[rt]={'error': repr(e)}
    return out

def tls_check(host, port=443):
    ctx=ssl.create_default_context(); t=time.time()
    try:
        with socket.create_connection((host, port), timeout=8) as sock:
            with ctx.wrap_socket(sock, server_hostname=host) as s:
                cert=s.getpeercert()
                return {'ok': True, 'host': host, 'port': port, 'elapsed_sec': round(time.time()-t,3), 'version': s.version(), 'cipher': s.cipher(), 'subject': cert.get('subject'), 'issuer': cert.get('issuer'), 'notBefore': cert.get('notBefore'), 'notAfter': cert.get('notAfter'), 'san': cert.get('subjectAltName')}
    except Exception as e: return {'ok': False, 'host': host, 'port': port, 'error': repr(e)}

def headers(url):
    with httpx.Client(http2=True, follow_redirects=False, timeout=15, headers={'user-agent':'arena-agent-recon-lab/0.1'}) as c:
        r=c.get(url)
    return {'ok': True, 'url': str(r.url), 'status_code': r.status_code, 'http_version': r.http_version, 'headers': dict(r.headers)}

def fetch_text(url):
    with httpx.Client(http2=True, follow_redirects=True, timeout=20, headers={'user-agent':'arena-agent-recon-lab/0.1'}) as c:
        r=c.get(url)
    return r

def robots(url):
    u=urlparse(url if '://' in url else 'https://'+url)
    base=f'{u.scheme}://{u.netloc}/'
    r=fetch_text(urljoin(base,'robots.txt'))
    return {'ok': True, 'url': str(r.url), 'status_code': r.status_code, 'text': r.text[:30000]}

def sitemap(url):
    u=urlparse(url if '://' in url else 'https://'+url)
    base=f'{u.scheme}://{u.netloc}/'
    candidates=[urljoin(base,'sitemap.xml'), urljoin(base,'sitemap_index.xml')]
    found=[]
    for cnd in candidates:
        try:
            r=fetch_text(cnd); found.append({'url': str(r.url), 'status_code': r.status_code, 'content_type': r.headers.get('content-type'), 'text_preview': r.text[:10000]})
        except Exception as e: found.append({'url': cnd, 'error': repr(e)})
    return {'ok': True, 'base': base, 'candidates': found}

def tech(url):
    r=fetch_text(url); text=r.text[:200000]; h=dict(r.headers)
    sig=[]; low=text.lower()
    checks={
        'wordpress':['wp-content','wp-includes','/wp-json'], 'nextjs':['__next','/_next/'], 'nuxt':['__nuxt','/_nuxt/'], 'react':['react','data-reactroot'], 'vue':['vue','__vue__'], 'svelte':['svelte'], 'cloudflare':['cf-ray','cloudflare'], 'vercel':['x-vercel','vercel'], 'nginx':['nginx'], 'apache':['apache'], 'jquery':['jquery']
    }
    hay=low+'\n'+json.dumps(h).lower()
    for name, needles in checks.items():
        if any(n in hay for n in needles): sig.append(name)
    scripts=re.findall(r'<script[^>]+src=["\']([^"\']+)', text, flags=re.I)[:100]
    metas=re.findall(r'<meta[^>]+(?:name|property)=["\']([^"\']+)["\'][^>]+content=["\']([^"\']*)', text, flags=re.I)[:100]
    return {'ok': True, 'url': str(r.url), 'status_code': r.status_code, 'http_version': r.http_version, 'server': h.get('server'), 'x_powered_by': h.get('x-powered-by'), 'signatures': sig, 'scripts': scripts, 'metas': metas}

def main():
    p=argparse.ArgumentParser(); sub=p.add_subparsers(dest='cmd', required=True)
    s=sub.add_parser('dns'); s.add_argument('domain'); s.add_argument('--types', nargs='*', default=['A','AAAA','MX','NS','TXT','CAA','SOA']); s.set_defaults(func=lambda a: j({'ok':True,'domain':a.domain,'dns':dns_lookup(a.domain,a.types)}))
    s=sub.add_parser('tls'); s.add_argument('host'); s.add_argument('--port', type=int, default=443); s.set_defaults(func=lambda a: j(tls_check(a.host,a.port)))
    s=sub.add_parser('headers'); s.add_argument('url'); s.set_defaults(func=lambda a: j(headers(a.url)))
    s=sub.add_parser('robots'); s.add_argument('url'); s.set_defaults(func=lambda a: j(robots(a.url)))
    s=sub.add_parser('sitemap'); s.add_argument('url'); s.set_defaults(func=lambda a: j(sitemap(a.url)))
    s=sub.add_parser('tech'); s.add_argument('url'); s.set_defaults(func=lambda a: j(tech(a.url)))
    args=p.parse_args(); args.func(args)
if __name__=='__main__': main()
