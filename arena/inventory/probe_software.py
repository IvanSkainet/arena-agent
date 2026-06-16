"""Inventory probe group extracted from scripts/inventory.py."""
from __future__ import annotations

from arena.inventory.probe_common import *  # noqa: F401,F403

def get_runtimes() -> dict:
    found: dict[str, str] = {}
    for name in RUNTIMES:
        # Some need -v / -version instead of --version
        if name == "node":
            v = _ver(name, "--version")
        elif name in ("java", "javac"):
            # java -version writes to stderr
            v = _ver(name, "-version")
        elif name == "scala":
            v = _ver(name, "-version")
        elif name == "lua":
            v = _ver(name, "-v")
        elif name == "dotnet":
            # `dotnet --version` may print an error banner if only partial
            # runtime bits are present. `--info` gives a cleaner first line.
            v = _ver(name, "--version")
            if v and ("dotnet" not in v.lower() and not v[0].isdigit()):
                info = _run([_which(name) or name, "--info"], timeout=5, capture_stderr=True)
                for ln in info.splitlines():
                    if ln.strip().lower().startswith((".net sdk", ".net runtimes", "host:")):
                        v = ln.strip(); break
        else:
            v = _ver(name)
        if v:
            found[name] = v
    return found

def get_package_managers() -> dict:
    found: dict[str, str] = {}
    for name in PACKAGE_MANAGERS:
        if name == "snap":
            v = _ver(name, "version")
        elif name == "winget":
            v = _ver(name, "--version")
        elif name == "scoop":
            # scoop is a PowerShell function in some shells; check PATH only
            p = _which("scoop")
            if p:
                v = p
            else:
                continue
        else:
            v = _ver(name)
        if v:
            found[name] = v
    return found

def get_browsers() -> dict:
    found: dict[str, str] = {}
    sys_name = platform.system()
    # First PATH-based check (works on Linux/macOS)
    for name in BROWSERS:
        v = _ver(name, "--version", timeout=4)
        if v:
            found[name] = v
    if sys_name == "Windows":
        for p in WINDOWS_BROWSER_PATHS:
            if os.path.isfile(p):
                # Try to get version via PowerShell file properties
                name = Path(p).stem
                vers = _run(_powershell_utf8_command(
                    f"(Get-Item '{p}').VersionInfo.ProductVersion"
                ), timeout=5).strip()
                found[name + " (exe)"] = f"{p} {('v' + vers) if vers else ''}".strip()
    elif sys_name == "Darwin":
        for app in MACOS_BROWSER_APPS:
            if os.path.isdir(app):
                # Read CFBundleShortVersionString from Info.plist
                plist = Path(app) / "Contents" / "Info.plist"
                vers = ""
                if plist.exists():
                    try:
                        import plistlib
                        with open(plist, "rb") as f:
                            d = plistlib.load(f)
                        vers = d.get("CFBundleShortVersionString", "")
                    except Exception:
                        pass
                found[Path(app).stem] = f"{app}" + (f" v{vers}" if vers else "")
    return found

def get_env() -> dict:
    env: dict[str, str] = {}
    for k in ENV_KEYS_OF_INTEREST:
        v = os.environ.get(k)
        if v is not None:
            env[k] = v
    # Trim PATH to make it readable
    if "PATH" in env:
        sep = os.pathsep
        parts = env["PATH"].split(sep)
        env["PATH_entries"] = len(parts)
        env["PATH_dirs"] = parts
    return env

def get_services() -> dict:
    sys_name = platform.system()
    info: dict[str, Any] = {}
    if sys_name == "Linux":
        out = _run(["systemctl", "--user", "--no-pager",
                    "--no-legend", "list-units", "--type=service",
                    "--state=running"], timeout=5)
        units = []
        for line in out.splitlines():
            parts = line.split()
            if parts and parts[0].endswith(".service"):
                units.append(parts[0])
        info["systemd_user_running"] = units
    elif sys_name == "Darwin":
        out = _run(["launchctl", "list"], timeout=5)
        agents = []
        for line in out.splitlines()[1:]:
            parts = line.split("\t")
            if len(parts) >= 3 and parts[2].strip().startswith("com."):
                agents.append(parts[2].strip())
        info["launchctl_loaded"] = agents[:50]  # cap
    elif sys_name == "Windows":
        out = _run(["schtasks", "/Query", "/FO", "CSV", "/NH"], timeout=10)
        tasks = []
        for line in out.splitlines():
            parts = [p.strip('"') for p in line.split('","')]
            if parts and parts[0].startswith("\\"):
                tasks.append(parts[0].lstrip("\\"))
        # Filter Arena-related tasks
        info["scheduled_tasks_arena"] = [t for t in tasks if "arena" in t.lower()]
        info["scheduled_tasks_total"] = len(tasks)
    return info

def get_python_env() -> dict:
    info: dict[str, Any] = {
        "executable": sys.executable,
        "version": platform.python_version(),
        "implementation": platform.python_implementation(),
        "prefix": sys.prefix,
        "base_prefix": sys.base_prefix,
        "is_venv": sys.prefix != sys.base_prefix,
        "argv": sys.argv,
        "site_packages": [],
        "installed_pkgs_count": None,
    }
    try:
        import site
        info["site_packages"] = list(site.getsitepackages()) if hasattr(site, "getsitepackages") else []
    except Exception:
        pass
    # Try pip list (best-effort)
    pip_path = _which("pip3") or _which("pip")
    if pip_path:
        out = _run([pip_path, "list", "--format=freeze"], timeout=10)
        if out:
            pkgs = [p for p in out.splitlines() if "==" in p]
            info["installed_pkgs_count"] = len(pkgs)
            info["installed_pkgs_top20"] = pkgs[:20]
    return info
