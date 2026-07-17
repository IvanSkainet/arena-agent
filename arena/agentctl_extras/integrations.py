"""agentctl extras MCP/beep integration commands."""
from __future__ import annotations

from arena.agentctl_extras.common import *  # noqa: F401,F403
from arena.agentctl_extras.actions import play_notification_sound

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
                except Exception: pass
                
        custom_dur = None
        if "--duration" in args:
            idx = args.index("--duration")
            if idx + 1 < len(args):
                try: custom_dur = int(args[idx+1])
                except Exception: pass

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
            # v4.42.0: switched from os.system() -- see the same
            # change in arena/agentctl_extras/actions.py for the
            # rationale (no-shell subprocess.run is refactor-safe).
            import subprocess
            subprocess.run(['osascript', '-e', 'beep'], check=False)
        else:
            sys.stdout.write("\a")
            sys.stdout.flush()
        print(f"[OK] Played {beep_type} sound notification.")
        return 0
    except Exception as e:
        print(f"Error playing beep: {e}", file=sys.stderr)
        return 1
