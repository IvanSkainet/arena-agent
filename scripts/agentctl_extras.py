#!/usr/bin/env python3
# Arena Agent — CLI Extras v4.3 (Cross-platform)
import os
import sys
import json
import time
import subprocess
import shutil
import platform
import socket
from pathlib import Path

ROOT = Path(os.environ.get("ARENA_AGENT_HOME", os.path.expanduser("~/arena-bridge")))
AGENTCTL = ROOT / "bin" / "agentctl"

# Cross-platform Python finder (venv or system)
_VENV_CANDIDATES = [
    ROOT / ".venv" / "bin" / "python",
    ROOT / ".venv" / "Scripts" / "python.exe",
]
PY = next((c for c in _VENV_CANDIDATES if c.exists()), None)
if PY is None:
    for cmd in [sys.executable, "python3", "python"]:
        p = shutil.which(cmd)
        if p:
            PY = Path(p)
            break
    else:
        PY = Path("python3")

def run_status(args=[]):
    import urllib.request
    import subprocess
    print("### bridge health local")
    try:
        r = urllib.request.urlopen("http://127.0.0.1:8765/health", timeout=2)
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
            r = urllib.request.urlopen(req, timeout=2)
            mcp_ok = r.status == 200
            print(f"  MCP Streamable HTTP: {'OK' if mcp_ok else 'FAIL'}")
        except: print("  MCP Streamable HTTP: FAIL")
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
        os.system("systemctl --user --no-pager status arena-unified-bridge.service 2>/dev/null | head -n 100 || true")
    elif platform.system() == "Windows":
        for svc_info in [
            ("ArenaUnifiedBridge", "unified-bridge (all services on :8765)"),
        ]:
            svc_name, desc = svc_info
            try:
                r = subprocess.run(["schtasks", "/query", "/tn", svc_name, "/fo", "TABLE"], capture_output=True, text=True, timeout=5)
                running = "Running" in r.stdout or "Выполняется" in r.stdout or "Running" in r.stdout
                state = "running" if running and _check_port(8765) == "LISTEN" else "stopped"
            except: state = "unknown"
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

def play_notification_sound():
    try:
        import platform
        import sys
        if platform.system() == "Windows":
            import winsound
            winsound.MessageBeep(winsound.MB_ICONASTERISK)
        elif platform.system() == "Darwin":
            import os
            os.system('osascript -e "beep"')
        else:
            sys.stdout.write("\a")
            sys.stdout.flush()
    except Exception:
        pass

def cmd_do(args: list[str]) -> int:
    if not args:
        print("usage: agentctl do '<shell command>'", file=sys.stderr)
        return 2
    cmd_str = args[0] if len(args) == 1 else " ".join(args)
    python = shutil.which("python3") or shutil.which("python") or sys.executable
    cp = subprocess.run([python, str(AGENTCTL), "task-submit", cmd_str], capture_output=True, text=True)
    if cp.returncode != 0:
        print(f"Error submitting task: {cp.stderr}", file=sys.stderr)
        return cp.returncode
    
    # FIXED (v4.3): Extract base filename as task_id to avoid path separator / vs \ conflicts on Windows!
    task_path = cp.stdout.strip()
    task_id = os.path.basename(task_path).replace(".json", "")
    print(f"submitted: {task_id}")
    
    # Wait for result
    for _ in range(600):
        time.sleep(1)
        cp2 = subprocess.run([python, str(AGENTCTL), "task", "show", task_id], capture_output=True, text=True)
        if cp2.returncode == 0:
            try:
                task = json.loads(cp2.stdout)
                if task.get("state") in ["done", "failed"]:
                    print(task.get("stdout", ""))
                    if task.get("stderr"):
                        print(task.get("stderr"), file=sys.stderr)
                    try: play_notification_sound()
                    except Exception: pass
                    return 0 if task.get("state") == "done" else 1
            except Exception:
                pass
    print("timeout waiting for task execution", file=sys.stderr)
    return 1

def cmd_tail(args: list[str]) -> int:
    kind = args[0] if args else "audit"
    n = int(args[1]) if len(args) > 1 else 20
    if kind == "audit":
        p = ROOT / "logs" / "audit.jsonl"
        if not p.exists():
            p = Path.home() / "arena-bridge" / "audit.jsonl"
    else:
        p = ROOT / "logs" / f"{kind}.jsonl"
    
    if not p.exists():
        print(f"log file not found: {p}", file=sys.stderr)
        return 1
    
    # Simple cross-platform tail
    try:
        lines = p.read_text(encoding="utf-8", errors="ignore").splitlines()
        for line in lines[-n:]:
            print(line)
    except Exception as e:
        print(f"Error reading log: {e}", file=sys.stderr)
        return 1
    return 0

def cmd_find(args: list[str]) -> int:
    if not args:
        print("usage: agentctl find <pattern>", file=sys.stderr)
        return 2
    pattern = args[0].lower()
    count = 0
    # Search in sessions, reports, skills
    for folder in [ROOT / "memory" / "sessions", ROOT / "reports"]:
        if not folder.exists(): continue
        for fp in folder.glob("**/*"):
            if fp.is_file() and fp.suffix in [".json", ".jsonl", ".txt", ".md"]:
                try:
                    content = fp.read_text(encoding="utf-8", errors="ignore")
                    if pattern in content.lower() or pattern in fp.name.lower():
                        print(f"Match found in: {fp.relative_to(ROOT)}")
                        count += 1
                except Exception:
                    pass
    print(f"Total matches: {count}")
    return 0

def cmd_remember(args: list[str]) -> int:
    if len(args) < 2:
        print("usage: agentctl remember <key> <value> [--tags tag1,tag2]", file=sys.stderr)
        return 2
    key = args[0]
    val = args[1]
    tags = []
    if "--tags" in args:
        idx = args.index("--tags")
        if idx + 1 < len(args):
            tags = args[idx+1].split(",")
    
    facts_file = ROOT / "memory" / "facts.jsonl"
    facts_file.parent.mkdir(parents=True, exist_ok=True)
    fact = {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "key": key,
        "val": val,
        "tags": tags
    }
    try:
        with open(facts_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(fact, ensure_ascii=False) + "\n")
        print(f"[OK] Remembered fact: {key}")
    except Exception as e:
        print(f"Error writing fact: {e}", file=sys.stderr)
        return 1
    return 0

def cmd_doctor_fix(_args: list[str]) -> int:
    fixed: list[str] = []
    issues: list[str] = []
  
    # 1. Ensure critical dirs exist  
    for d in (ROOT / "memory" / "sessions", ROOT / "logs",  
              ROOT / "skills", ROOT / "reports", ROOT / "backups",  
              ROOT / "queue" / "inbox", ROOT / "queue" / "running",  
              ROOT / "queue" / "done", ROOT / "queue" / "failed"):  
        if not d.exists():  
            d.mkdir(parents=True, exist_ok=True)  
            fixed.append(f"created {d}")  
        if platform.system() != "Windows":  
            try:  
                mode = d.stat().st_mode & 0o777  
                if mode != 0o700:  
                    d.chmod(0o700)  
                    fixed.append(f"chmod 700 {d} (was {oct(mode)})")  
            except OSError as e:  
                issues.append(f"chmod {d}: {e}")  
  
    # 2. Fix permissions on data files in memory/sessions (non-Windows)  
    if platform.system() != "Windows":  
        sd = ROOT / "memory" / "sessions"  
        if sd.is_dir():  
            for f in sd.glob("*.jsonl"):  
                try:  
                    mode = f.stat().st_mode & 0o777  
                    if mode != 0o600:  
                        f.chmod(0o600)  
                        fixed.append(f"chmod 600 {f.name}")  
                except OSError as e:  
                    issues.append(f"chmod {f}: {e}")  
  
    # 3. Check unified bridge via port reachability (cross-platform)
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(2)
    ok = s.connect_ex(("127.0.0.1", 8765)) == 0
    s.close()
    if not ok:
        issues.append("unified-bridge (port 8765) not reachable")
    else:
        fixed.append("unified-bridge (port 8765): OK")  
  
    # 4. Verify agentctl python syntax  
    cp = subprocess.run([sys.executable, "-m", "py_compile", str(AGENTCTL)],  
                        capture_output=True, text=True)  
    if cp.returncode != 0:  
        issues.append(f"agentctl syntax: {cp.stderr.strip()}")  
    else:  
        fixed.append("agentctl syntax: OK")  
  
    # 5. Platform-specific service checks  
    if platform.system() == "Linux" and shutil.which("systemctl"):  
        for svc in ["arena-bridge.service", "arena-task-runner.service"]:  
            cp = subprocess.run(["systemctl", "--user", "is-active", svc],  
                                capture_output=True, text=True)  
            if cp.stdout.strip() != "active":  
                issues.append(f"{svc} not active")  
  
    print("=== fixes applied ===")  
    for f in fixed:  
        print(f"  + {f}")  
    if not fixed:  
        print("  (nothing to fix)")  
    if issues:  
        print("\n=== remaining issues (manual attention) ===")  
        for i in issues:  
            print(f"  ! {i}")  
        return 1  
    print("\nAll auto-fixable issues resolved.")  
    return 0

def cmd_update(args: list[str]) -> int:
    has_git = shutil.which("git") is not None  
    if has_git:  
        print("=== Checking updates via Git ===")  
        res = subprocess.run(["git", "pull"], cwd=str(ROOT), capture_output=True, text=True)  
        print(res.stdout)  
        if res.stderr.strip():  
            print("Details:", res.stderr)  
    else:  
        print("=== Git not found ===")  
        print("To update manually: unpack the new release archive over your existing")  
        print("arena-bridge folder, then run update.bat (Windows) or update.sh (Linux).")  
  
    if platform.system() == "Linux":  
        installer = ROOT / "scripts" / "install_linux_service.sh"  
        if installer.exists():  
            print("=== Re-running Linux services installer ===")  
            subprocess.run(["bash", str(installer)], cwd=str(ROOT))  
        else:  
            print("=== Restarting systemd services ===")  
            subprocess.run(["systemctl", "--user", "daemon-reload"])  
            services = ["arena-bridge.service", "arena-mcp-stream.service", "arena-mcp-ws.service", "arena-task-runner.service", "arena-web-gateway.service"]  
            subprocess.run(["systemctl", "--user", "restart"] + services)  
    elif platform.system() == "Windows":  
        installer = ROOT / "scripts" / "install_windows_service.ps1"  
        if installer.exists():  
            print("=== Re-running Windows installer ===")  
            subprocess.run(["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(installer)], cwd=str(ROOT))  
        else:  
            print("=== Windows services ===")  
            print("Run 'update.bat' in the arena-bridge folder to restart all services.")  
    else:  
        print("Please restart the agent services manually on this platform.")  
  
    print("\nUpdate completed successfully!")  
    return 0

def cmd_mcp_install(args: list[str]) -> int:  
    if not args:  
        print("usage: agentctl mcp install <npm-package-or-alias>", file=sys.stderr)  
        print("examples:", file=sys.stderr)  
        print("  agentctl mcp install desktop-commander", file=sys.stderr)  
        print("  agentctl mcp install @modelcontextprotocol/filesystem", file=sys.stderr)  
        return 2  
    alias = args[0]  
    known = {  
        "desktop-commander": "@anthropic-ai/desktop-commander",  
        "filesystem": "@modelcontextprotocol/filesystem",  
        "sqlite": "@modelcontextprotocol/sqlite",  
        "fetch": "@modelcontextprotocol/fetch",  
    }  
    pkg = known.get(alias, alias)  
    mcp_dir = ROOT / "mcp"  
    mcp_dir.mkdir(parents=True, exist_ok=True)  
    cfg_path = mcp_dir / "mcp.json"  
    cfg = json.loads(cfg_path.read_text(encoding="utf-8")) if cfg_path.exists() else {"mcpServers": {}}  
    if "mcpServers" not in cfg:  
        cfg["mcpServers"] = {}  
    if alias not in cfg["mcpServers"]:  
        cfg["mcpServers"][alias] = {"command": "npx", "args": ["-y", pkg], "env": {}}  
        cfg_path.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")  
        print(f"[OK] Registered '{alias}' -> npx -y {pkg} in {cfg_path}")  
    else:  
        print(f"'{alias}' already registered in mcp.json")  
    npm = shutil.which("npm")  
    npx = shutil.which("npx")  
    if npm or npx:  
        print("[INFO] Installing / verifying package via npm...")  
        r = subprocess.run(["npm", "install", "-g", pkg], capture_output=True, text=True)  
        if r.returncode != 0:  
            print(f"[WARN] npm install -g returned {r.returncode}: {r.stderr.strip()[:200]}")  
            print("[INFO] npx will download the package on first run automatically.")  
        else:  
            print("[OK] Package ready.")  
    else:  
        print("[WARN] npm/npx not found. Install Node.js from https://nodejs.org/ first.")  
    print("[INFO] Restart MCP services to pick up new servers:")  
    print("       Windows:  Start-ScheduledTask -TaskName ArenaMcpStream; Start-ScheduledTask -TaskName ArenaMcpWs")  
    print("       Linux:    systemctl --user restart arena-mcp-stream.service arena-mcp-ws.service")  
    return 0

def cmd_beep(args: list[str]) -> int:
    try:
        import platform
        import sys
        import time
        
        beep_type = "success"
        if "--type" in args:
            idx = args.index("--type")
            if idx + 1 < len(args):
                beep_type = args[idx+1].lower()
                
        custom_freq = None
        if "--frequency" in args:
            idx = args.index("--frequency")
            if idx + 1 < len(args):
                try: custom_freq = int(args[idx+1])
                except: pass
                
        custom_dur = None
        if "--duration" in args:
            idx = args.index("--duration")
            if idx + 1 < len(args):
                try: custom_dur = int(args[idx+1])
                except: pass

        if platform.system() == "Windows":
            import winsound
            if custom_freq and custom_dur:
                winsound.Beep(custom_freq, custom_dur)
            else:
                if beep_type == "error":
                    winsound.Beep(330, 250)
                    time.sleep(0.05)
                    winsound.Beep(262, 400)
                elif beep_type == "warning":
                    for _ in range(3):
                        winsound.Beep(440, 150)
                        time.sleep(0.05)
                elif beep_type == "attention":
                    winsound.Beep(1000, 100)
                    time.sleep(0.05)
                    winsound.Beep(1000, 100)
                elif beep_type == "melody":
                    winsound.Beep(523, 120)
                    winsound.Beep(659, 120)
                    winsound.Beep(784, 150)
                else:
                    # success (happy double beep)
                    winsound.Beep(523, 120)
                    time.sleep(0.05)
                    winsound.Beep(659, 150)
        elif platform.system() == "Darwin":
            import os
            os.system('osascript -e "beep"')
        else:
            sys.stdout.write("\a")
            sys.stdout.flush()
        print(f"[OK] Played {beep_type} sound notification.")
        return 0
    except Exception as e:
        print(f"Error playing beep: {e}", file=sys.stderr)
        return 1

DISPATCH = {
    "beep": cmd_beep,
    "status": run_status,
    "ctx": cmd_ctx,
    "do": cmd_do,
    "tail": cmd_tail,
    "find": cmd_find,
    "remember": cmd_remember,
    "doctor-fix": cmd_doctor_fix,
    "doctor": cmd_doctor_fix,
    "update": cmd_update,
    "mcp-install": cmd_mcp_install,
}

def main() -> int:
    if len(sys.argv) < 2:
        print("usage: agentctl_extras.py <subcmd> [args...]", file=sys.stderr)
        return 2
    cmd = sys.argv[1]
    fn = DISPATCH.get(cmd)
    if not fn:
        print(f"unknown subcmd: {cmd}", file=sys.stderr)
        return 2
    return fn(sys.argv[2:])

if __name__ == "__main__":
    sys.exit(main())