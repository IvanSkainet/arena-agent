#!/usr/bin/env python3
from pathlib import Path
p=Path.home()/"arena-agent/scripts/agentctl_extras.py"
s=p.read_text()
start=s.index("def run_status")
end=s.index("import re", start)
new='''def run_status(args=[]):
    import urllib.request, json, os
    print("### bridge health local")
    try:
        r = urllib.request.urlopen("http://127.0.0.1:8765/health", timeout=2); print(r.read().decode().strip())
    except Exception as e: print(f"local health error: {e}")
    print(); print("### mcp stream health")
    try:
        r = urllib.request.urlopen("http://127.0.0.1:8767/health", timeout=2); print(r.read().decode().strip())
    except Exception as e: print(f"mcp stream error: {e}")
    print(); print("### port 8765/8767")
    os.system("ss -ltnp 'sport = :8765 or sport = :8767' 2>/dev/null || true")
    print(); print("### tailscale funnel")
    os.system("tailscale funnel status 2>/dev/null || true")
    print(); print("### cgroup memory hint (MB)")
    cg="/sys/fs/cgroup/user.slice/user-1000.slice/user@1000.service/app.slice/arena-local-bridge.service/memory.stat"
    if os.path.exists(cg):
        vals={}
        for line in open(cg):
            k,v=line.split()[:2]
            if k in ["anon","file","inactive_file","kernel","slab"]: vals[k]=int(v)//(1024*1024)
        print(json.dumps(vals, ensure_ascii=False))
    print(); print("### services")
    os.system("systemctl --user --no-pager status arena-local-bridge.service arena-task-runner.service arena-mcp-stream.service 2>/dev/null | head -n 100 || true")

'''
s=s[:start]+new+s[end:]
p.write_text(s); p.chmod(0o700)
print('fixed agentctl_extras')
