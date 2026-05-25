#!/usr/bin/env python3
from __future__ import annotations
import datetime as dt, json, os, subprocess, sys
from pathlib import Path
ROOT=Path(os.environ.get('ARENA_AGENT_HOME', str(Path.home()/'arena-agent'))).expanduser(); REPORTS=ROOT/'reports'
def run(cmd, timeout=60):
    p=subprocess.run(cmd, shell=True, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout)
    try: data=json.loads(p.stdout)
    except Exception: data={'exit_code':p.returncode,'stdout':p.stdout,'stderr':p.stderr}
    return data
def main():
    if len(sys.argv)<2: raise SystemExit('usage: recon_report.py DOMAIN')
    domain=sys.argv[1].strip().removeprefix('https://').removeprefix('http://').split('/')[0]
    REPORTS.mkdir(parents=True, exist_ok=True); st=dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    data={'ok':True,'domain':domain,'generated_at':dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds')}
    base=f'{ROOT}/bin/agentctl'
    data['dns']=run(f'{base} dns-check {domain}',30)
    data['tls']=run(f'{base} tls-check {domain}',30)
    data['headers']=run(f'{base} headers https://{domain}',30)
    data['robots']=run(f'{base} robots https://{domain}',30)
    data['sitemap']=run(f'{base} sitemap https://{domain}',40)
    data['tech']=run(f'{base} tech-detect https://{domain}',40)
    json_path=REPORTS/f'recon-report-{domain}-{st}.json'; md_path=REPORTS/f'recon-report-{domain}-{st}.md'
    json_path.write_text(json.dumps(data, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    lines=[f'# Recon report: {domain}','',f'Generated: {data["generated_at"]}','',f'- JSON: `{json_path}`','']
    for section in ['dns','tls','headers','tech','robots','sitemap']:
        lines += [f'## {section}', '', '```json', json.dumps(data.get(section), ensure_ascii=False, indent=2)[:12000], '```', '']
    md_path.write_text('\n'.join(lines), encoding='utf-8')
    os.chmod(json_path,0o600); os.chmod(md_path,0o600)
    print(json.dumps({'ok':True,'domain':domain,'json':str(json_path),'markdown':str(md_path)}, ensure_ascii=False, indent=2))
if __name__=='__main__': main()
