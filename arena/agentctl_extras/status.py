"""agentctl extras status/context commands."""
from __future__ import annotations

from arena.agentctl_extras.common import *  # noqa: F401,F403

def run_status(args=[]):
    import urllib.request
    import subprocess
    print("### bridge health local")
    try:
        r = urllib.request.urlopen("http://127.0.0.1:8765/health", timeout=2)  # nosec B310 -- loopback bridge URL for local status check  # nosemgrep: dynamic-urllib-use-detected -- URL either loopback / fixed internal endpoint OR routed through arena.security_ssrf._validate_url (see bandit B310 nosec on the same line for the specific rationale)
        print(r.read().decode().strip())
    except Exception as e:
        print(f"local health error: {e}")

    print()
    print("### unified bridge port 8765")
    def _check_port(port):
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(1)
        ok = s.connect_ex(("127.0.0.1", port)) == 0
        s.close()
        return "LISTEN" if ok else "closed"
    p8765 = _check_port(8765)
    print(f":8765 {p8765}  (bridge + MCP + SSE + WS + gateway + dashboard)")
    if p8765 == "LISTEN":
        # Verify MCP sub-endpoints on unified bridge
        try:
            import urllib.request
            req = urllib.request.Request("http://127.0.0.1:8765/mcp",
                data=json.dumps({"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"health-check","version":"1.0"}}}).encode(),
                headers={"Content-Type":"application/json"})
            r = urllib.request.urlopen(req, timeout=2)  # nosec B310 -- loopback bridge URL for local status check  # nosemgrep: dynamic-urllib-use-detected -- URL either loopback / fixed internal endpoint OR routed through arena.security_ssrf._validate_url (see bandit B310 nosec on the same line for the specific rationale)
            mcp_ok = r.status == 200
            print(f"  MCP Streamable HTTP: {'OK' if mcp_ok else 'FAIL'}")
        except Exception: print("  MCP Streamable HTTP: FAIL")
    else:
        print("  All sub-services: DOWN (bridge not running)")

    print()
    print("### tailscale funnel")
    if shutil.which("tailscale"):
        try:
            if platform.system() == "Windows":
                subprocess.run("tailscale funnel status 2>nul || tailscale serve status 2>nul", shell=True)
            else:
                subprocess.run("tailscale funnel status 2>/dev/null || tailscale serve status 2>/dev/null || true", shell=True)
        except Exception as e:
            print(f"Failed to check Tailscale: {e}")
    else:
        print("tailscale not found in PATH")

    print()
    print("### platform info")
    os_ver = (f"Windows 11" if platform.system() == "Windows" and int(platform.version().split('.')[-1]) >= 22000 else f"Windows 10" if platform.system() == "Windows" else platform.system())
    print(f"system={os_ver}  build={platform.version().split('.')[-1]}  node={platform.node()}  release={platform.release()}")
    
    print()
    print("### hardware info (HWiNFO / AIDA64 style)")
    try:
        hw_script = os.path.join(ROOT, "scripts", "hwinfo.py")
        if os.path.exists(hw_script):
            res_hw = subprocess.run([sys.executable, hw_script], capture_output=True, text=True)
            if res_hw.returncode == 0:
                h_data = json.loads(res_hw.stdout)
                # Print OS
                print(f"  OS:       {h_data['os']['name_pretty']} (Build {h_data['os']['build']}) {h_data['os']['architecture']}")
                # Motherboard
                m = h_data.get('motherboard', {})
                if m: print(f"  Board:    {m.get('manufacturer', '')} {m.get('product', '')} (BIOS: {m.get('bios_name', '')})")
                # CPU
                c = h_data.get('cpu', {})
                if c: print(f"  CPU:      {c.get('name', '')} ({c.get('physical_cores', '')} Cores / {c.get('logical_processors', '')} Threads)")
                # GPU
                g = h_data.get('gpu', [])
                if g and len(g) >= 3:
                    gpu_name = next((item["name"] for item in g if "name" in item), "?")
                    gpu_ram = next((item["vram_mb"] for item in g if "vram_mb" in item), "?")
                    print(f"  GPU:      {gpu_name} ({gpu_ram} MB VRAM)")
                # RAM
                r = h_data.get('ram', {})
                if r: print(f"  RAM:      {r.get('used_gb', '')} GB used / {r.get('total_gb', '')} GB total ({r.get('used_pct', '')}% used)")
                # Disks
                d = h_data.get('storage', {})
                if d:
                    print("  Disks:")
                    for cap, details in d.items():
                        print(f"    - Drive {cap}  {details['free_gb']} GB free of {details['total_gb']} GB ({details['filesystem']}, {details['used_pct']}% used)")
                # Network
                net = h_data.get('network', {}).get('adapters', [])
                if net:
                    print("  Network:")
                    for adapter in net:
                        print(f"    - {adapter.get('InterfaceAlias', '')}: {adapter.get('IPAddress', '')}")
            else:
                print("  Failed to run hwinfo.py")
        else:
            print("  hwinfo.py not found.")
    except Exception as e:
        print(f"  Error loading hardware info: {e}")
    print()
    print("### services (unified bridge)")
    if platform.system() == "Linux" and shutil.which("systemctl"):
        # v4.42.0: was os.system(...). Switched to argv-form
        # subprocess so refactors that add a variable into the
        # command cannot accidentally introduce shell injection.
        # We still want the "|| true" behaviour (do not raise if
        # the unit doesn't exist), so check=False is explicit.
        # The pipe-to-head-100 is replaced with a Python-side
        # slice since we no longer have a shell.
        try:
            _sc = subprocess.run(
                ["systemctl", "--user", "--no-pager", "status",
                 "arena-unified-bridge.service"],
                capture_output=True, text=True, check=False, timeout=10,
            )
            out = _sc.stdout or ""
            for line in out.splitlines()[:100]:
                print(line)
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass
    elif platform.system() == "Windows":
        for svc_info in [
            ("ArenaUnifiedBridge", "unified-bridge (all services on :8765)"),
        ]:
            svc_name, desc = svc_info
            try:
                r = subprocess.run(["schtasks", "/query", "/tn", svc_name, "/fo", "TABLE"], capture_output=True, text=True, timeout=5)
                running = "Running" in r.stdout or "Выполняется" in r.stdout or "Running" in r.stdout
                state = "running" if running and _check_port(8765) == "LISTEN" else "stopped"
            except Exception: state = "unknown"
            print(f"  - {desc}: {state}")
        # Also check if bridge is reachable even without scheduled task
        if _check_port(8765) == "LISTEN":
            print(f"  - bridge health: OK (port 8765 open, all services multiplexed)")
    else:
        if _check_port(8765) == "LISTEN":
            print("  - unified bridge: running (port 8765)")
        else:
            print("  - unified bridge: not running")

def cmd_ctx(_args: list[str]) -> int:
    python = shutil.which("python3") or shutil.which("python") or sys.executable
    return subprocess.call([python, str(AGENTCTL), "skill", "run", "core/digest"])
