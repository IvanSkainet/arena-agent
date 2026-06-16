"""agentctl extras maintenance commands."""
from __future__ import annotations

from arena.agentctl_extras.common import *  # noqa: F401,F403

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
