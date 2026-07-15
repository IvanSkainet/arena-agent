"""System state probes for AI agents (v3.88.5 split).

Split out of probe_agent_ctx.py so both files stay under the
MAX_RUNTIME_LINES limit. Same discipline: never raise, always
return {"available": bool, ...}.
"""
from __future__ import annotations

from arena.inventory.probe_common import *  # noqa: F401,F403


# ------------------------------------------------------------------ dns_resolvers

def get_dns_resolvers() -> dict:
    """/etc/resolv.conf, /etc/hosts summary, systemd-resolved status."""
    info: dict[str, Any] = {"available": False}
    sys_name = platform.system()

    if sys_name in ("Linux", "Darwin"):
        rc = Path("/etc/resolv.conf")
        nameservers: list[str] = []
        search: list[str] = []
        if rc.is_file():
            try:
                for ln in rc.read_text(encoding="utf-8",
                                        errors="replace").splitlines():
                    ln = ln.strip()
                    if ln.startswith("nameserver"):
                        parts = ln.split()
                        if len(parts) >= 2:
                            nameservers.append(parts[1])
                    elif ln.startswith("search"):
                        search = ln.split()[1:]
            except Exception:
                pass
        info["nameservers"] = nameservers
        info["search"] = search

        hosts = Path("/etc/hosts")
        if hosts.is_file():
            try:
                count = 0
                for ln in hosts.read_text(encoding="utf-8",
                                           errors="replace").splitlines():
                    ln = ln.strip()
                    if ln and not ln.startswith("#"):
                        count += 1
                info["hosts_entry_count"] = count
            except Exception:
                pass

        if sys_name == "Linux" and _which("resolvectl"):
            out = _run(["resolvectl", "status", "--no-pager"], timeout=3)
            info["resolvectl"] = out[:2000] if out else None

    elif sys_name == "Windows":
        # ipconfig /all prints DNS servers per adapter
        out = _run(["ipconfig", "/all"], timeout=5)
        dns = []
        for m in re.finditer(r"DNS Servers[^\n]*:\s*(\S+)", out):
            dns.append(m.group(1))
        info["nameservers"] = dns

    info["available"] = bool(info.get("nameservers") or info.get("hosts_entry_count"))
    return info


# ------------------------------------------------------------------ dmesg_errors

def get_dmesg_errors(limit: int = 30) -> dict:
    """Recent kernel-level errors from dmesg / journalctl -k. Linux only."""
    info: dict[str, Any] = {"available": False, "errors": []}
    if platform.system() != "Linux":
        info["error"] = "dmesg is Linux-only"
        return info

    # `journalctl -k -p err -n 30` is the modern way; falls back to dmesg.
    if _which("journalctl"):
        out = _run(["journalctl", "-k", "-p", "err", "-n", str(limit),
                    "--no-pager", "-o", "short-iso"], timeout=5)
        if "No entries" not in out and out.strip():
            for ln in out.splitlines():
                ln = ln.strip()
                if ln and not ln.startswith("--") and _has_message_body(ln):
                    info["errors"].append(ln[:200])
            info["available"] = True
            return info

    if _which("dmesg"):
        out = _run(["dmesg", "--level=err,crit,alert,emerg",
                    "--time-format=iso", "-T"], timeout=4)
        for ln in out.splitlines()[-limit:]:
            ln = ln.strip()
            if _has_message_body(ln):
                info["errors"].append(ln[:200])
        info["available"] = True

    if not info["errors"]:
        info["error"] = "no readable kernel log source"
    return info


def _has_message_body(line: str) -> bool:
    """Skip journalctl / dmesg lines whose payload after
    ``kernel:`` / ``systemd[1]:`` / ``progname[pid]:`` is empty.

    A syslog-style line looks like::

        <iso-timestamp> <host> <ident>[<pid>]: <body>

    We find the LAST match of ``ident[pid]:`` (so ISO timestamps
    with their own colons don't fool us) and check whether anything
    non-empty follows. Empty body = skip.
    """
    line = (line or "").strip()
    if not line:
        return False
    matches = list(re.finditer(r"[a-zA-Z0-9_\-.]+(?:\[\d+\])?:", line))
    if not matches:
        # No syslog-shape prefix -- assume it's already a plain message.
        return True
    last = matches[-1]
    body = line[last.end():].strip()
    return bool(body)


# ------------------------------------------------------------------ journal_errors

def get_journal_errors(limit: int = 30) -> dict:
    """Recent systemd service errors (Linux only)."""
    info: dict[str, Any] = {"available": False, "errors": []}
    if platform.system() != "Linux":
        info["error"] = "journalctl is Linux-only"
        return info
    if not _which("journalctl"):
        info["error"] = "journalctl not on PATH"
        return info

    out = _run(["journalctl", "-p", "err", "-n", str(limit),
                "--no-pager", "-o", "short-iso", "--since", "1 hour ago"],
                timeout=6)
    for ln in out.splitlines():
        ln = ln.strip()
        if ln and not ln.startswith(("--", "No entries")) and _has_message_body(ln):
            info["errors"].append(ln[:200])
    info["available"] = True
    return info


# ------------------------------------------------------------------ virtualization

def get_virtualization() -> dict:
    """Detect bare-metal / VM / container / WSL2. Agents choose different
    strategies for I/O-heavy work depending on this."""
    info: dict[str, Any] = {"available": False, "type": "unknown",
                             "hypervisor": None, "container": None}
    sys_name = platform.system()

    if sys_name == "Linux":
        if _which("systemd-detect-virt"):
            hv = _run(["systemd-detect-virt", "--vm"], timeout=2).strip()
            ct = _run(["systemd-detect-virt", "--container"], timeout=2).strip()
            info["hypervisor"] = hv if hv and hv != "none" else None
            info["container"] = ct if ct and ct != "none" else None
        # WSL2: kernel string contains 'microsoft'
        try:
            release = Path("/proc/sys/kernel/osrelease").read_text().lower()
            if "microsoft" in release:
                info["container"] = "wsl"
        except Exception:
            pass
        # /.dockerenv is a well-known docker marker
        if Path("/.dockerenv").exists():
            info["container"] = info["container"] or "docker"
        # Deduce type
        if info["container"]:
            info["type"] = "container"
        elif info["hypervisor"]:
            info["type"] = "vm"
        else:
            info["type"] = "bare-metal"
        info["available"] = True

    elif sys_name == "Darwin":
        # macOS: sysctl kern.hv_vmm_present -> non-zero means guest
        out = _run(["sysctl", "-n", "kern.hv_vmm_present"], timeout=2)
        try:
            info["type"] = "vm" if int(out.strip()) else "bare-metal"
        except Exception:
            info["type"] = "unknown"
        info["available"] = True

    elif sys_name == "Windows":
        # PowerShell: (Get-CimInstance Win32_ComputerSystem).Model
        # returns "Virtual Machine" on Hyper-V etc.
        ps = "(Get-CimInstance Win32_ComputerSystem).Model"
        out = _run(_powershell_utf8_command(ps), timeout=5).strip()
        info["model"] = out
        low = out.lower()
        if "virtual" in low or "vmware" in low or "kvm" in low:
            info["type"] = "vm"
        else:
            info["type"] = "bare-metal"
        info["available"] = True

    return info


# ------------------------------------------------------------------ time_sync

def get_time_sync() -> dict:
    """NTP status: source, offset, drift. Agents that stamp events or
    verify TLS certs care about clock accuracy."""
    info: dict[str, Any] = {"available": False}
    sys_name = platform.system()

    if sys_name == "Linux":
        if _which("timedatectl"):
            out = _run(["timedatectl", "show"], timeout=3)
            for ln in out.splitlines():
                k, _, v = ln.partition("=")
                if k and v:
                    info[k.strip()] = v.strip()
            # Also try `timedatectl timesync-status` for offset (needs
            # systemd-timesyncd -- not chrony/ntpd).
            ts = _run(["timedatectl", "timesync-status", "--no-pager"], timeout=3)
            for ln in ts.splitlines():
                if ":" in ln:
                    k, _, v = ln.partition(":")
                    info[k.strip().lower().replace(" ", "_")] = v.strip()
            info["available"] = True
            return info
        if _which("chronyc"):
            out = _run(["chronyc", "tracking"], timeout=3)
            for ln in out.splitlines():
                if ":" in ln:
                    k, _, v = ln.partition(":")
                    info[k.strip().lower().replace(" ", "_")] = v.strip()
            info["available"] = bool(info)

    elif sys_name == "Darwin":
        out = _run(["sntp", "-t", "2", "time.apple.com"], timeout=4)
        if out.strip():
            info["output"] = out.strip()[:400]
            info["available"] = True

    elif sys_name == "Windows":
        out = _run(["w32tm", "/query", "/status"], timeout=5)
        if out.strip():
            for ln in out.splitlines():
                if ":" in ln:
                    k, _, v = ln.partition(":")
                    info[k.strip().lower().replace(" ", "_")] = v.strip()
            info["available"] = bool(info)

    return info


# ------------------------------------------------------------------ firewall_status

def get_firewall_status() -> dict:
    """Detect the active firewall backend and count rules."""
    info: dict[str, Any] = {"available": False, "backend": None,
                             "active": None, "rule_summary": {}}
    sys_name = platform.system()

    if sys_name == "Linux":
        # ufw first (Debian/Ubuntu), then firewalld (RHEL family),
        # then plain iptables/nftables.
        if _which("ufw"):
            out = _run(["ufw", "status"], timeout=3)
            info["backend"] = "ufw"
            info["active"] = "active" in out.lower()
            info["rule_summary"]["lines"] = len(out.splitlines())
        elif _which("firewall-cmd"):
            state = _run(["firewall-cmd", "--state"], timeout=3).strip()
            info["backend"] = "firewalld"
            info["active"] = state == "running"
            info["rule_summary"]["default_zone"] = _run(
                ["firewall-cmd", "--get-default-zone"], timeout=2).strip()
        elif _which("nft"):
            out = _run(["nft", "list", "ruleset"], timeout=4)
            info["backend"] = "nftables"
            info["active"] = bool(out.strip())
            info["rule_summary"]["rule_lines"] = len(out.splitlines())
        elif _which("iptables"):
            out = _run(["iptables", "-L", "-n"], timeout=4)
            info["backend"] = "iptables"
            info["active"] = "Chain " in out
            # Count non-default lines
            rules = sum(1 for ln in out.splitlines()
                         if ln.strip() and not ln.startswith(("Chain", "target")))
            info["rule_summary"]["rule_count"] = rules
        info["available"] = info["backend"] is not None
        if not info["available"]:
            info["error"] = "no known Linux firewall CLI on PATH"

    elif sys_name == "Darwin":
        # pfctl requires root; socketfilterfw is user-accessible.
        if _which("socketfilterfw"):
            out = _run(["socketfilterfw", "--getglobalstate"], timeout=3)
            info["backend"] = "pf/alf"
            info["active"] = "enabled" in out.lower()
            info["available"] = True

    elif sys_name == "Windows":
        ps = "(Get-NetFirewallProfile | Select-Object Name,Enabled | ConvertTo-Json -Compress)"
        out = _run(_powershell_utf8_command(ps), timeout=5)
        try:
            data = json.loads(out) if out else []
            if isinstance(data, dict):
                data = [data]
            info["backend"] = "windows-defender-firewall"
            info["profiles"] = [{"name": d.get("Name"),
                                  "enabled": bool(d.get("Enabled"))}
                                 for d in data]
            info["active"] = any(p["enabled"] for p in info["profiles"])
            info["available"] = True
        except Exception:
            pass

    return info
