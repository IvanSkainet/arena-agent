#!/usr/bin/env python3
from pathlib import Path
root=Path.home()/'arena-agent'
# Patch dashboard Streamable test.
p=root/'dashboard/index.html'
s=p.read_text()
old=s[s.find('async function testStreamable()'):s.find('setInterval(loadSys', s.find('async function testStreamable()'))]
new=r'''async function testStreamable() {
    const out = document.getElementById('stream-out');
    const base = getPortHost(8767);
    out.textContent = "Testing MCP Streamable HTTP + legacy SSE on port 8767...\n";
    try {
        // 1) Direct Streamable HTTP POST to /mcp (modern MCP transport)
        out.textContent += "-> POST /mcp initialize...\n";
        let init = await fetch(base + '/mcp', {
            method: 'POST',
            headers: {"Content-Type":"application/json", "Accept":"application/json, text/event-stream"},
            body: JSON.stringify({jsonrpc:"2.0", id:1, method:"initialize", params:{}})
        });
        out.textContent += `-> /mcp status: ${init.status}\n`;
        out.textContent += (await init.text()).slice(0, 600) + "\n";
        out.textContent += "-> POST /mcp tools/list...\n";
        let tools = await fetch(base + '/mcp', {
            method: 'POST',
            headers: {"Content-Type":"application/json", "Accept":"application/json, text/event-stream"},
            body: JSON.stringify({jsonrpc:"2.0", id:2, method:"tools/list"})
        });
        out.textContent += `-> tools status: ${tools.status}\n`;
        out.textContent += (await tools.text()).slice(0, 600) + "\n";

        // 2) Legacy SSE endpoint. Important: first event is custom 'endpoint', not onmessage.
        let streamUrl = base + '/sse';
        out.textContent += `-> EventSource ${streamUrl}...\n`;
        let es = new EventSource(streamUrl);
        let closed = false;
        const closeSoon = () => setTimeout(() => { if(!closed){ closed=true; es.close(); out.textContent += "-> SSE closed after successful probe.\n"; } }, 3000);
        es.onopen = () => { out.textContent += "-> SSE open\n"; };
        es.addEventListener('endpoint', async (e) => {
            out.textContent += `-> endpoint event: ${e.data}\n`;
            let postUrl = base + e.data;
            let r = await fetch(postUrl, {method:'POST', headers:{"Content-Type":"application/json"}, body:JSON.stringify({jsonrpc:"2.0", id:3, method:"tools/call", params:{name:"ping", arguments:{}}})});
            out.textContent += `-> legacy POST status: ${r.status}\n`;
            closeSoon();
        });
        es.addEventListener('message', (e) => { out.textContent += `-> message: ${e.data}\n`; });
        es.onerror = () => { if(!closed) out.textContent += "-> SSE error/closed. If status above is 200, this can be normal after probe close.\n"; closed=true; es.close(); };
        setTimeout(() => { if(!closed){ closed=true; es.close(); out.textContent += "-> SSE timeout close.\n"; } }, 8000);
    } catch(e) { out.textContent += "Error: " + e.message + "\n"; }
}

'''
if old and 'POST /mcp initialize' not in s:
    s=s.replace(old,new)
p.write_text(s)
# Patch task runner to not spam journal in watch mode.
p=root/'scripts/task_runner.py'
s=p.read_text()
s=s.replace("def run_once(args):\n    ensure()\n    count = 0", "def run_once(args):\n    ensure()\n    count = 0")
s=s.replace("    if count == 0: print('no tasks')", "    if count == 0 and not getattr(args, 'quiet', False): print('no tasks')")
s=s.replace("        run_once(argparse.Namespace(max=args.max))", "        run_once(argparse.Namespace(max=args.max, quiet=True))")
p.write_text(s); p.chmod(0o700)
# Patch status extras: include mcp stream and compact cgroup memory.
p=root/'scripts/agentctl_extras.py'
s=p.read_text()
old='''def run_status(args=[]):
    import urllib.request, json
    print("### bridge health local")
    try:
        r = urllib.request.urlopen("http://127.0.0.1:8765/health", timeout=2)
        print(r.read().decode().strip())
    except: pass
    print("\n### bridge health funnel")
    try:
        r = urllib.request.urlopen(os.environ.get("ARENA_BRIDGE_URL", "https://cachyos-x8664.tail328f18.ts.net") + "/health", timeout=3)
        print(r.read().decode().strip())
    except: pass
    print("\n### port 8765")
    os.system("ss -ltnp 'sport = :8765' 2>/dev/null || true")
    print("\n### tailscale funnel")
    os.system("tailscale funnel status 2>/dev/null || true")
    print("\n### services")
    os.system("systemctl --user --no-pager status arena-local-bridge.service arena-task-runner.service 2>/dev/null | head -n 80 || true")
'''
new='''def run_status(args=[]):
    import urllib.request, json, os, subprocess
    print("### bridge health local")
    try:
        r = urllib.request.urlopen("http://127.0.0.1:8765/health", timeout=2); print(r.read().decode().strip())
    except Exception as e: print(f"local health error: {e}")
    print("\n### mcp stream health")
    try:
        r = urllib.request.urlopen("http://127.0.0.1:8767/health", timeout=2); print(r.read().decode().strip())
    except Exception as e: print(f"mcp stream error: {e}")
    print("\n### port 8765/8767")
    os.system("ss -ltnp 'sport = :8765 or sport = :8767' 2>/dev/null || true")
    print("\n### tailscale funnel")
    os.system("tailscale funnel status 2>/dev/null || true")
    print("\n### cgroup memory hint")
    cg='/sys/fs/cgroup/user.slice/user-1000.slice/user@1000.service/app.slice/arena-local-bridge.service/memory.stat'
    if os.path.exists(cg):
        vals={}
        for line in open(cg):
            k,v=line.split()[:2]
            if k in ['anon','file','inactive_file','kernel','slab']: vals[k]=int(v)//(1024*1024)
        print(json.dumps(vals, ensure_ascii=False))
    print("\n### services")
    os.system("systemctl --user --no-pager status arena-local-bridge.service arena-task-runner.service arena-mcp-stream.service 2>/dev/null | head -n 100 || true")
'''
if old in s: s=s.replace(old,new)
p.write_text(s); p.chmod(0o700)
print('patched dashboard/status/task')
