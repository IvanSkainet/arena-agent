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
