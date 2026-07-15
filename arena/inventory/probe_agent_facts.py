"""Probes that expose runtime state useful to AI agents planning work.

These are things an agent typically wants to know before it starts
a task: what's already using CPU/RAM, what ports are taken, when
did the box last boot, which services just crashed, which kernel
modules are loaded (for hardware-specific driver checks).

Each probe returns ``{"available": bool, ...}`` and never raises.
Cross-platform where feasible; degrades to ``available: False``
gracefully.
"""
from __future__ import annotations

from arena.inventory.probe_common import *  # noqa: F401,F403


# ------------------------------------------------------------------ top_processes

def get_top_processes(limit: int = 10) -> dict:
    """Top ``limit`` processes by CPU and by RAM. Uses psutil so it's
    identical on Linux, macOS, Windows.

    Two lists are returned because the same process rarely wins both
    -- and agents want to know "who is holding memory" separately
    from "who is burning CPU right now".
    """
    info: dict[str, Any] = {"available": False, "by_cpu": [], "by_memory": []}
    try:
        import psutil  # type: ignore
    except Exception:
        info["error"] = "psutil not installed"
        return info

    procs: list[dict[str, Any]] = []
    # Prime CPU percent counters -- first call always returns 0.0.
    for p in psutil.process_iter(["pid", "name"]):
        try:
            p.cpu_percent(None)
        except Exception:
            pass
    # Give the sampler a moment to measure real deltas.
    import time
    time.sleep(0.15)

    for p in psutil.process_iter(["pid", "name", "username", "cpu_percent",
                                    "memory_info", "status", "cmdline"]):
        try:
            info_p = p.info
            mem = info_p.get("memory_info")
            cmd = info_p.get("cmdline") or []
            procs.append({
                "pid": info_p.get("pid"),
                "name": info_p.get("name") or "",
                "user": info_p.get("username") or "",
                "cpu_pct": round(float(info_p.get("cpu_percent") or 0), 1),
                "rss_mb": round((getattr(mem, "rss", 0) or 0) / 1_048_576, 1),
                "status": info_p.get("status") or "",
                "cmd": " ".join(cmd[:6])[:180] if cmd else "",
            })
        except Exception:
            continue

    if not procs:
        return info

    info["by_cpu"] = sorted(procs, key=lambda x: x["cpu_pct"], reverse=True)[:limit]
    info["by_memory"] = sorted(procs, key=lambda x: x["rss_mb"], reverse=True)[:limit]
    info["available"] = True
    info["total_process_count"] = len(procs)
    return info


# ------------------------------------------------------------------ listening_ports

def get_listening_ports() -> dict:
    """Open TCP/UDP listeners with owning process. Agents use this
    before binding a port and before assuming ``localhost:8765`` is
    theirs."""
    info: dict[str, Any] = {"available": False, "tcp": [], "udp": []}
    try:
        import psutil  # type: ignore
    except Exception:
        info["error"] = "psutil not installed"
        return info

    pid_names: dict[int, str] = {}
    try:
        for p in psutil.process_iter(["pid", "name"]):
            pid_names[p.info["pid"]] = p.info.get("name") or ""
    except Exception:
        pass

    try:
        conns = psutil.net_connections(kind="inet")
    except (PermissionError, psutil.AccessDenied) as e:
        info["error"] = f"net_connections requires root on this platform: {e}"
        return info
    except Exception as e:
        info["error"] = f"{type(e).__name__}: {e}"
        return info

    for c in conns:
        if c.status != psutil.CONN_LISTEN and (c.type != 2):  # SOCK_DGRAM=2
            # For UDP, most sockets are technically "listening" without
            # the LISTEN state -- keep them anyway.
            if c.type != 2:
                continue
        laddr = c.laddr
        if not laddr:
            continue
        entry = {
            "addr": str(laddr.ip),
            "port": int(laddr.port),
            "pid": c.pid,
            "process": pid_names.get(c.pid or 0, ""),
        }
        if c.type == 1:  # SOCK_STREAM
            info["tcp"].append(entry)
        elif c.type == 2:
            info["udp"].append(entry)

    info["tcp"].sort(key=lambda x: x["port"])
    info["udp"].sort(key=lambda x: x["port"])
    info["available"] = bool(info["tcp"] or info["udp"])
    return info


# ------------------------------------------------------------------ systemd_failed

def get_systemd_failed() -> dict:
    """Systemd units in ``failed`` state (Linux only). Agents can spot
    that Docker just died before trying to run a container.
    """
    info: dict[str, Any] = {"available": False, "system_failed": [], "user_failed": []}
    if platform.system() != "Linux":
        info["error"] = "systemd is Linux-only"
        return info
    if not _which("systemctl"):
        info["error"] = "systemctl not on PATH"
        return info

    for scope, key in (("--system", "system_failed"), ("--user", "user_failed")):
        out = _run(["systemctl", scope, "list-units", "--failed", "--no-legend",
                     "--plain", "--no-pager"], timeout=4)
        for line in out.splitlines():
            parts = line.split(None, 4)
            if len(parts) >= 4 and parts[3] == "failed":
                info[key].append({
                    "unit": parts[0],
                    "load": parts[1],
                    "active": parts[2],
                    "description": parts[4] if len(parts) > 4 else "",
                })
    info["available"] = True
    return info


# ------------------------------------------------------------------ boot_time

def get_boot_time() -> dict:
    """Machine boot time + uptime. psutil is authoritative across all
    three OSes."""
    info: dict[str, Any] = {"available": False}
    try:
        import psutil  # type: ignore
        from datetime import datetime, timezone
        bt = psutil.boot_time()
        now = datetime.now(timezone.utc).timestamp()
        info["available"] = True
        info["boot_time_epoch"] = int(bt)
        info["boot_time_iso"] = datetime.fromtimestamp(bt, tz=timezone.utc).isoformat()
        info["uptime_seconds"] = int(now - bt)
    except Exception as e:
        info["error"] = f"{type(e).__name__}: {e}"
    return info


# ------------------------------------------------------------------ kernel_modules

def get_kernel_modules(limit: int = 200) -> dict:
    """Loaded kernel modules (Linux only). Useful for the agent to
    know that ``nvidia_uvm`` is loaded before it tries CUDA, or that
    ``btrfs`` is loaded before it plans a snapshot.
    """
    info: dict[str, Any] = {"available": False, "modules": [], "count": 0}
    if platform.system() != "Linux":
        info["error"] = "kernel modules probe is Linux-only"
        return info

    p = Path("/proc/modules")
    if not p.exists():
        info["error"] = "/proc/modules not readable"
        return info

    try:
        text = p.read_text(encoding="utf-8", errors="replace")
    except Exception as e:
        info["error"] = f"{type(e).__name__}: {e}"
        return info

    entries: list[dict[str, Any]] = []
    for line in text.splitlines():
        parts = line.split()
        if len(parts) < 4:
            continue
        entries.append({
            "name": parts[0],
            "size_bytes": int(parts[1]) if parts[1].isdigit() else 0,
            "used_count": int(parts[2]) if parts[2].isdigit() else 0,
            "used_by": [] if parts[3] == "-" else parts[3].rstrip(",").split(","),
        })
    info["count"] = len(entries)
    # Return the largest N so the payload stays bounded on kernels
    # with 400+ modules loaded.
    entries.sort(key=lambda x: x["size_bytes"], reverse=True)
    info["modules"] = entries[:limit]
    info["available"] = True
    return info


# ------------------------------------------------------------------ containers

def get_containers() -> dict:
    """Docker / Podman containers with status + ports + image.

    Agents use this to know what services are already running before
    launching duplicates, and to spot recently-exited containers
    (``status='Exited (137)'``) that might be OOM-kills the agent
    should investigate before starting more work.

    Prefers ``docker`` when present, falls back to ``podman`` (both
    are drop-in CLI-compatible for our purposes). Neither on PATH ->
    ``available=False``.
    """
    info: dict[str, Any] = {"available": False, "containers": []}
    runtime = None
    for candidate in ("docker", "podman"):
        if _which(candidate):
            runtime = candidate
            break
    if not runtime:
        info["error"] = "neither docker nor podman on PATH"
        return info

    info["runtime"] = runtime
    out = _run([runtime, "ps", "-a", "--format", "{{json .}}"], timeout=6)
    if not out:
        info["available"] = True
        return info

    running = 0
    total = 0
    for line in out.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            c = json.loads(line)
        except Exception:
            continue
        total += 1
        status = str(c.get("Status", "") or c.get("State", ""))
        if status.startswith("Up ") or status.lower() == "running":
            running += 1
        info["containers"].append({
            "name": c.get("Names") or c.get("Name"),
            "image": c.get("Image"),
            "status": status,
            "ports": c.get("Ports", ""),
            "created": c.get("CreatedAt") or c.get("Created"),
        })
    info["running_count"] = running
    info["total_count"] = total
    info["available"] = True
    return info


# ------------------------------------------------------------------ systemd_timers

def get_systemd_timers(limit: int = 20) -> dict:
    """Active systemd timers with next/last fire time (Linux only)."""
    info: dict[str, Any] = {"available": False, "timers": []}
    if platform.system() != "Linux":
        info["error"] = "systemd is Linux-only"
        return info
    if not _which("systemctl"):
        info["error"] = "systemctl not on PATH"
        return info

    out = _run(["systemctl", "list-timers", "--all", "--no-legend",
                "--no-pager"], timeout=5)
    if not out:
        info["available"] = True
        return info

    for raw in out.splitlines()[:limit]:
        parts = re.split(r"\s{2,}", raw.strip())
        if len(parts) < 5:
            continue
        info["timers"].append({
            "next":     parts[0] if parts[0] != "-" else None,
            "left":     parts[1] if len(parts) > 1 else None,
            "last":     parts[2] if len(parts) > 2 and parts[2] != "-" else None,
            "passed":   parts[3] if len(parts) > 3 else None,
            "unit":     parts[4] if len(parts) > 4 else None,
            "activates": parts[5] if len(parts) > 5 else None,
        })
    info["available"] = True
    return info


# ------------------------------------------------------------------ network_io

def get_network_io() -> dict:
    """Cumulative RX/TX bytes / packets / errors / drops per interface."""
    info: dict[str, Any] = {"available": False, "interfaces": []}
    try:
        import psutil  # type: ignore
    except Exception:
        info["error"] = "psutil not installed"
        return info

    try:
        stats = psutil.net_io_counters(pernic=True)
    except Exception as e:
        info["error"] = f"{type(e).__name__}: {e}"
        return info

    for name, s in (stats or {}).items():
        if name in ("lo", "Loopback Pseudo-Interface 1"):
            continue
        info["interfaces"].append({
            "name": name,
            "bytes_sent": int(s.bytes_sent),
            "bytes_recv": int(s.bytes_recv),
            "packets_sent": int(s.packets_sent),
            "packets_recv": int(s.packets_recv),
            "errin": int(s.errin),
            "errout": int(s.errout),
            "dropin": int(s.dropin),
            "dropout": int(s.dropout),
        })
    info["available"] = bool(info["interfaces"])
    return info


# ------------------------------------------------------------------ updates_available

def get_updates_available() -> dict:
    """Number of pending package-manager updates (no installation)."""
    info: dict[str, Any] = {"available": False, "pending_count": None,
                            "manager": None, "sample": []}

    def _try_pacman() -> dict | None:
        if _which("checkupdates"):
            out = _run(["checkupdates"], timeout=6)
        elif _which("pacman"):
            out = _run(["pacman", "-Qu"], timeout=6)
        else:
            return None
        pkgs = [ln.strip() for ln in out.splitlines() if ln.strip()]
        sample = []
        for ln in pkgs[:8]:
            parts = ln.split()
            sample.append({"name": parts[0],
                           "new_version": parts[-1] if len(parts) > 1 else ""})
        return {"manager": "pacman", "pending_count": len(pkgs), "sample": sample}

    def _try_apt() -> dict | None:
        if not _which("apt"):
            return None
        out = _run(["apt", "list", "--upgradable"], timeout=8)
        pkgs = [ln for ln in out.splitlines()
                if ln and not ln.startswith("Listing") and "/" in ln]
        sample = []
        for ln in pkgs[:8]:
            name = ln.split("/", 1)[0]
            sample.append({"name": name, "new_version": ""})
        return {"manager": "apt", "pending_count": len(pkgs), "sample": sample}

    def _try_dnf() -> dict | None:
        if not _which("dnf"):
            return None
        out = _run(["dnf", "-q", "check-update"], timeout=10)
        pkgs = [ln.split()[0] for ln in out.splitlines()
                if ln and not ln.startswith(("Last", "Obsoleting"))
                and len(ln.split()) >= 3]
        sample = [{"name": p, "new_version": ""} for p in pkgs[:8]]
        return {"manager": "dnf", "pending_count": len(pkgs), "sample": sample}

    def _try_brew() -> dict | None:
        if not _which("brew"):
            return None
        out = _run(["brew", "outdated", "--quiet"], timeout=8)
        pkgs = [ln.strip() for ln in out.splitlines() if ln.strip()]
        sample = [{"name": p, "new_version": ""} for p in pkgs[:8]]
        return {"manager": "brew", "pending_count": len(pkgs), "sample": sample}

    def _try_winget() -> dict | None:
        if not _which("winget"):
            return None
        out = _run(["winget", "upgrade"], timeout=10)
        pkgs = [ln for ln in out.splitlines()
                if ln.strip() and not ln.startswith(("Name", "----"))]
        return {"manager": "winget", "pending_count": max(0, len(pkgs) - 2),
                "sample": []}

    from datetime import datetime, timezone
    for probe in (_try_pacman, _try_apt, _try_dnf, _try_brew, _try_winget):
        try:
            r = probe()
        except Exception as e:
            info["error"] = f"{probe.__name__}: {type(e).__name__}: {e}"
            continue
        if r is not None:
            info.update(r)
            info["available"] = True
            info["checked_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
            return info

    info["error"] = "no supported package manager found on PATH"
    return info


# ------------------------------------------------------------------ logged_users

def get_logged_users() -> dict:
    """Currently logged-in interactive sessions (cross-platform)."""
    info: dict[str, Any] = {"available": False, "users": []}
    try:
        import psutil  # type: ignore
    except Exception:
        info["error"] = "psutil not installed"
        return info

    try:
        users = psutil.users()
    except Exception as e:
        info["error"] = f"{type(e).__name__}: {e}"
        return info

    from datetime import datetime, timezone
    for u in users or []:
        started_iso = None
        try:
            started_iso = datetime.fromtimestamp(
                float(u.started), tz=timezone.utc
            ).isoformat(timespec="seconds")
        except Exception:
            pass
        info["users"].append({
            "name":     u.name,
            "terminal": u.terminal or "",
            "host":     u.host or "",
            "started":  started_iso,
            "pid":      getattr(u, "pid", None),
        })
    info["available"] = True
    return info


# ------------------------------------------------------------------ cpu_vulnerabilities

def get_cpu_vulnerabilities() -> dict:
    """CPU vulnerability mitigation status (Linux only).

    Reads /sys/devices/system/cpu/vulnerabilities/*. Agents planning
    security-sensitive workflows should check that Spectre / Meltdown /
    Retbleed / etc. are actually mitigated before assuming isolation
    is real.
    """
    info: dict[str, Any] = {"available": False, "mitigations": {}}
    if platform.system() != "Linux":
        info["error"] = "vulnerability sysfs is Linux-only"
        return info

    base = Path("/sys/devices/system/cpu/vulnerabilities")
    if not base.is_dir():
        info["error"] = "/sys/devices/system/cpu/vulnerabilities not present " \
                        "(kernel too old or non-x86)"
        return info

    for entry in sorted(base.iterdir()):
        try:
            info["mitigations"][entry.name] = entry.read_text(
                encoding="utf-8", errors="replace"
            ).strip()
        except Exception:
            info["mitigations"][entry.name] = "?"

    info["available"] = bool(info["mitigations"])
    return info
