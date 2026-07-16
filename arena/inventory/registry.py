"""Single source of truth for inventory sections.

Every inventory section is declared once here as a ``Section``
dataclass with:

  * ``name``       -- key used in ``/v1/inventory`` and ``/v1/hardware``
                      output. Also the ``?section=X`` filter value.
  * ``label``      -- human-readable name shown in the Full Inventory
                      checkbox strip and Cards.
  * ``category``   -- 'hardware', 'sensors', 'runtime', 'agent',
                      'software'. Used for grouping in UI.
  * ``collector``  -- callable that returns the section's dict.
  * ``format_lines(data) -> list[str]`` -- pure function that turns
                      the section's dict into text lines. When None,
                      the section is emitted verbatim as JSON in the
                      text formatter (rarely; almost every section
                      has one).

Downstream modules read from this registry instead of maintaining
their own lists:

  * ``arena/inventory/report.py``     -- SECTIONS = REGISTRY.as_sections()
  * ``arena/inventory/text_format.py`` -- one loop over REGISTRY
  * ``dashboard/assets/03b-hw-cards.js`` and
    ``dashboard/assets/22-full-inventory-loader.js`` fetch the
    registry via ``GET /v1/inventory/registry`` at boot and build
    the checkbox strip + cards mapping from it -- no more hand-
    maintained lists in HTML/JS.

Adding a new probe is now one edit: append a ``Section`` here.
Everything downstream picks it up.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Optional


LineFn = Callable[[dict], list[str]]


@dataclass(frozen=True)
class Section:
    name: str
    label: str
    category: str
    collector: Callable[[], dict]
    format_lines: Optional[LineFn] = None
    # Whether this section is included in the default Cards grid on
    # the Doctor tab (some are only interesting in Full Inventory).
    show_in_doctor: bool = True


# ---------------------------------------------------------------------
# Formatters. Each takes the section's collected dict and returns a
# list of "  key: value" lines. Section header (### Label) is added
# by the outer loop.
# ---------------------------------------------------------------------

def _fmt_identity(d: dict) -> list[str]:
    return [
        f"  user: {d.get('user', '?')}   host: {d.get('hostname', '?')}",
        f"  home: {d.get('home', '')}",
        *([f"  shell: {d.get('shell')}"] if d.get("shell") else []),
    ]


def _fmt_os(d: dict) -> list[str]:
    lines = [f"  {d.get('system')} {d.get('release')} ({d.get('machine')})"]
    if d.get("distro", {}).get("pretty"):
        lines.append(f"  distro: {d['distro']['pretty']}")
    if d.get("uptime_seconds"):
        u = d["uptime_seconds"]
        days, r = divmod(u, 86400); h, r = divmod(r, 3600); m, _ = divmod(r, 60)
        lines.append(f"  uptime: {days}d {h}h {m}m")
    lines.append(f"  python: {d.get('python_version')}")
    return lines


def _fmt_boot(d: dict) -> list[str]:
    if not d.get("available"):
        return []
    up = d.get("uptime_seconds", 0)
    days, r = divmod(up, 86400); h, r = divmod(r, 3600); m, _ = divmod(r, 60)
    return [f"  Booted   : {d.get('boot_time_iso', '')}",
            f"  Uptime   : {days}d {h}h {m}m"]


def _fmt_cpu(d: dict) -> list[str]:
    lines = [f"  {d.get('name', '(unknown)')}"]
    cores = d.get("cores_physical") or d.get("cores")
    threads = d.get("cores_logical") or d.get("threads")
    if cores or threads:
        line = f"  {cores or '?'} physical / {threads or '?'} logical cores"
        if d.get("max_ghz"):
            line += f", {d['max_ghz']} GHz max"
        lines.append(line)
    la = d.get("load_avg")
    if la and len(la) >= 3:
        lines.append(f"  load avg: {la[0]:.2f}, {la[1]:.2f}, {la[2]:.2f}")
    return lines


def _fmt_memory(d: dict) -> list[str]:
    lines = []
    if d.get("total_gb"):
        lines.append(
            f"  {d['total_gb']} GB total, "
            f"{d.get('used_gb', '?')} GB used, "
            f"{d.get('available_gb', '?')} GB free"
        )
    if d.get("swap_total_gb"):
        lines.append(f"  swap: {d.get('swap_free_gb', 0)} free / {d['swap_total_gb']} GB")
    for i, mod in enumerate(d.get("modules") or [], 1):
        lines.append(f"  slot {i}: {mod.get('size_gb')} GB "
                     f"{'@ ' + str(mod['speed_mhz']) + ' MHz' if mod.get('speed_mhz') else ''}"
                     f"{' — ' + mod['manufacturer'] if mod.get('manufacturer') else ''}")
    return lines


def _fmt_motherboard(d: dict) -> list[str]:
    lines = []
    mb = d.get("motherboard") or d
    if mb.get("manufacturer") or mb.get("product"):
        lines.append(f"  {mb.get('manufacturer', '')} {mb.get('product', '')}".strip())
    if mb.get("version"):
        lines.append(f"  rev {mb['version']}")
    bios = d.get("bios")
    if bios:
        lines.append(f"  BIOS: {bios.get('manufacturer', '')} v{bios.get('version', '')} "
                     f"({bios.get('release_date', '')})")
    return lines


def _fmt_gpu(d: dict) -> list[str]:
    lines = []
    for g in d.get("gpus") or []:
        line = f"  {g.get('name', '(unknown)')}"
        if g.get("vram_total_mb") or g.get("vram_mb"):
            line += f", {g.get('vram_total_mb') or g.get('vram_mb')} MB VRAM"
        if g.get("driver"):
            line += f" [{g['driver']}]"
        if g.get("temperature_c") is not None:
            line += f" {g['temperature_c']}°C"
        if g.get("utilization_pct") is not None:
            line += f" {g['utilization_pct']}% util"
        lines.append(line)
    return lines


def _fmt_disks(disks: list | dict) -> list[str]:
    if not disks: return []
    # Deduplicate btrfs subvolume noise
    by_dev: dict[str, tuple[dict, list]] = {}
    for d in (disks or []):
        key = d.get("device") or d.get("mount") or "?"
        if key not in by_dev:
            by_dev[key] = (d, [d.get("mount")] if d.get("mount") else [])
        else:
            if d.get("mount"): by_dev[key][1].append(d.get("mount"))
    lines = []
    for dev, (d, mounts) in by_dev.items():
        extra = f" (+{len(mounts) - 1} more mounts)" if len(mounts) > 1 else ""
        mount = d.get("mount") or d.get("device") or "?"
        lines.append(
            f"  {dev:<12}  {mount}{extra:<24} {d.get('filesystem', '?'):<8}  "
            f"{d.get('free_gb', '?')}/{d.get('total_gb', '?')} GB free "
            f"({d.get('used_pct', '?')}% used)"
        )
    return lines


def _fmt_thermal_detail(d: dict) -> list[str]:
    if not d.get("available"): return []
    lines = []
    by_class: dict[str, list] = {}
    for s in d.get("sensors", []):
        by_class.setdefault(s.get("class", "other"), []).append(s)
    for cls in ("cpu", "gpu", "nvme", "board", "other"):
        for s in by_class.get(cls, []):
            extra = ""
            crit = s.get("critical_c")
            hi = s.get("high_c")
            if crit and crit < 200: extra = f" (crit {crit}°C)"
            elif hi and hi < 200: extra = f" (high {hi}°C)"
            lines.append(f"  [{cls}] {s.get('label')}: {s.get('celsius')}°C{extra}")
    return lines


def _fmt_thermal(d: dict) -> list[str]:
    if not d or not d.get("temperatures"): return []
    return [f"  {t.get('type') or t.get('source')}: {t.get('celsius')}°C"
            for t in d.get("temperatures", [])[:12]]


def _fmt_fans(d: dict) -> list[str]:
    if not d.get("available"): return []
    return [f"  {f.get('label')}: {f.get('rpm')} RPM"
            for f in d.get("fans", [])]


def _fmt_battery(d: dict) -> list[str]:
    if not d.get("available"): return []
    lines = []
    if d.get("percent") is not None:
        lines.append(f"  Charge    : {d['percent']}% "
                     f"({'AC' if d.get('plugged') else 'discharging'})")
    for bat in d.get("batteries", []):
        parts = [x for x in (bat.get("manufacturer"), bat.get("model_name"),
                              bat.get("technology")) if x]
        if parts: lines.append(f"  Device    : {' / '.join(parts)}")
        if bat.get("health_pct") is not None:
            lines.append(f"  Health    : {bat['health_pct']}%")
        if bat.get("cycle_count") is not None:
            lines.append(f"  Cycles    : {bat['cycle_count']}")
    return lines


def _fmt_disk_smart(d: dict) -> list[str]:
    if not d.get("available"): return []
    lines = []
    for x in d.get("devices", []):
        status = "PASS" if x.get("passed") else "FAIL" if x.get("passed") is False else "?"
        lines.append(f"  {x.get('device')} [{status}] {x.get('model') or ''}")
        details = []
        for k, label in (("temperature_c", "°C"), ("power_on_hours", "h"),
                           ("percent_used", "% used"), ("available_spare_pct", "% spare"),
                           ("reallocated_sectors", " reallocated")):
            if x.get(k) is not None: details.append(f"{x[k]}{label}")
        if details: lines.append(f"    {' · '.join(details)}")
        if x.get("hint"): lines.append(f"    hint: {x['hint']}")
    return lines


def _fmt_audio(d: dict) -> list[str]:
    if not d.get("available"): return []
    lines = []
    for s in d.get("sinks", [])[:10]:
        lines.append(f"  out: {s.get('name', '')}")
    for s in d.get("sources", [])[:10]:
        lines.append(f"  in : {s.get('name', '')}")
    return lines


def _fmt_top_processes(d: dict) -> list[str]:
    if not d.get("available"): return []
    lines = []
    for p in d.get("by_cpu", [])[:5]:
        lines.append(f"  cpu {p['cpu_pct']:>5.1f}% · {p['rss_mb']:>7.1f} MB · "
                     f"{p['name']} (pid {p['pid']})")
    for p in d.get("by_memory", [])[:5]:
        lines.append(f"  ram {p['rss_mb']:>7.1f} MB · {p['cpu_pct']:>5.1f}% · "
                     f"{p['name']} (pid {p['pid']})")
    return lines


def _fmt_listening_ports(d: dict) -> list[str]:
    if not d.get("available"): return []
    return [f"  tcp/{p['port']:<6} {p.get('process', ''):<20} "
            f"pid {p.get('pid', '?')}  {p.get('addr', '')}"
            for p in d.get("tcp", [])[:25]]


def _fmt_systemd_failed(d: dict) -> list[str]:
    if not d.get("available"): return []
    failed = (d.get("system_failed") or []) + (d.get("user_failed") or [])
    if not failed: return ["  (none — clean state)"]
    return [f"  {u['unit']} — {u.get('description', '')}" for u in failed[:20]]


def _fmt_kernel_modules(d: dict) -> list[str]:
    if not d.get("available"): return []
    modules = d.get("modules", [])
    return [f"  {m['name']:<28} {m['size_bytes']:>10} B  used by {m['used_count']}"
            for m in modules[:15]]


def _fmt_containers(d: dict) -> list[str]:
    if not d.get("available"): return []
    lines = []
    for x in d.get("containers", [])[:15]:
        lines.append(f"  {(x.get('name') or '?'):<30} {x.get('status', '')}")
        if x.get("image"): lines.append(f"    image : {x['image']}")
        if x.get("ports"): lines.append(f"    ports : {x['ports'][:100]}")
    return lines or ["  (no containers)"]


def _fmt_systemd_timers(d: dict) -> list[str]:
    if not d.get("available"): return []
    return [f"  {(t.get('unit') or '?'):<40} next: {t.get('next') or '—'}"
            for t in d.get("timers", [])[:15]]


def _fmt_network_io(d: dict) -> list[str]:
    if not d.get("available"): return []
    lines = []
    for i in d.get("interfaces", []):
        def _b(n):
            for unit, div in (("TB", 1099511627776), ("GB", 1073741824),
                               ("MB", 1048576), ("KB", 1024)):
                if n >= div: return f"{n / div:.2f} {unit}"
            return f"{n} B"
        extra = ""
        if i["errin"] + i["errout"]: extra += f"  err {i['errin']+i['errout']}"
        if i["dropin"] + i["dropout"]: extra += f"  drop {i['dropin']+i['dropout']}"
        lines.append(f"  {i['name']:<20} ↓ {_b(i['bytes_recv']):<12} "
                     f"↑ {_b(i['bytes_sent'])}{extra}")
    return lines


def _fmt_updates(d: dict) -> list[str]:
    if not d.get("available"): return []
    pc = d.get("pending_count")
    lines = [f"  Manager  : {d.get('manager', '?')}",
             f"  Pending  : {pc if pc is not None else '?'}"]
    if d.get("checked_at"): lines.append(f"  Checked  : {d['checked_at']}")
    for p in d.get("sample", [])[:8]:
        if p.get("new_version"): lines.append(f"    {p['name']:<28} -> {p['new_version']}")
        else: lines.append(f"    {p['name']}")
    return lines


def _fmt_logged_users(d: dict) -> list[str]:
    if not d.get("available"): return []
    lines = []
    for u in d.get("users", []):
        parts = [u.get("terminal") or ""]
        if u.get("host"): parts.append(f"from {u['host']}")
        if u.get("started"): parts.append(u["started"])
        lines.append(f"  {(u.get('name') or '?'):<12} {'  '.join(p for p in parts if p)}")
    return lines or ["  (no active sessions)"]


def _fmt_cpu_vulns(d: dict) -> list[str]:
    if not d.get("available"): return []
    return [f"  {name:<22} {str(status).split(';')[0].strip()}"
            for name, status in (d.get("mitigations") or {}).items()]


def _fmt_virt(d: dict) -> list[str]:
    if not d.get("available"): return []
    lines = [f"  Type       : {d.get('type', 'unknown')}"]
    if d.get("hypervisor"): lines.append(f"  Hypervisor : {d['hypervisor']}")
    if d.get("container"):  lines.append(f"  Container  : {d['container']}")
    if d.get("model"):      lines.append(f"  Model      : {d['model']}")
    return lines


def _fmt_time_sync(d: dict) -> list[str]:
    if not d.get("available"): return []
    interesting = ("NTPSynchronized", "ntp_synchronized", "server",
                   "reference_time", "offset", "stratum", "leap_status",
                   "Timezone", "poll_interval")
    return [f"  {k:<20} {d[k]}" for k in interesting if d.get(k)]


def _fmt_firewall(d: dict) -> list[str]:
    if not d.get("available"): return []
    lines = [f"  Backend  : {d.get('backend', '?')}",
             f"  Active   : {'yes' if d.get('active') else 'no'}"]
    for p in d.get("profiles", []):
        lines.append(f"    {p['name']:<12} {'enabled' if p['enabled'] else 'disabled'}")
    for k, v in (d.get("rule_summary") or {}).items():
        lines.append(f"    {k:<20} {v}")
    return lines


def _fmt_dns(d: dict) -> list[str]:
    if not d.get("available"): return []
    lines = [f"  ns{i+1}       : {ns}" for i, ns in enumerate(d.get("nameservers", []))]
    if d.get("search"): lines.append(f"  search    : {' '.join(d['search'])}")
    if d.get("hosts_entry_count") is not None:
        lines.append(f"  hosts     : {d['hosts_entry_count']} entries")
    return lines


def _fmt_env_secrets(d: dict) -> list[str]:
    if not d.get("available"): return []
    lines = ["  (values are NEVER exposed -- only variable names)"]
    for name in d.get("names", []):
        lines.append(f"  cred: {name}")
    for name in d.get("file_refs", []):
        lines.append(f"  file: {name}")
    return lines


def _fmt_python_venvs(d: dict) -> list[str]:
    if not d.get("available"): return []
    return [f"  [{(env.get('python_version') or '?').split()[0]:<10}] "
            f"{env.get('path', '?')} · {env.get('package_count', 0)} pkgs"
            for env in d.get("venvs", [])]


def _fmt_git_repos(d: dict) -> list[str]:
    if not d.get("available"): return []
    lines = []
    for r in d.get("repos", []):
        parts = [f"branch={r.get('branch', '?')}"]
        if r.get("dirty_files") is not None: parts.append(f"dirty={r['dirty_files']}")
        if r.get("ahead") is not None and r.get("behind") is not None:
            parts.append(f"↑{r['ahead']} ↓{r['behind']}")
        lines.append(f"  {r.get('path', '?')}")
        lines.append(f"    {' · '.join(parts)}")
        if r.get("last_commit"): lines.append(f"    last: {r['last_commit']}")
    return lines


def _fmt_crontab(d: dict) -> list[str]:
    if not d.get("available"): return []
    lines = []
    for e in d.get("user_entries") or []: lines.append(f"  [user] {e}")
    for e in (d.get("system_entries") or [])[:15]: lines.append(f"  [sys]  {e}")
    return lines


def _fmt_error_list(d: dict) -> list[str]:
    """Shared formatter for dmesg_errors + journal_errors."""
    if not d.get("available"): return []
    errs = d.get("errors", [])
    if not errs: return ["  (clean)"]
    return [f"  {e}" for e in errs[:15]]


def _fmt_network(d: dict) -> list[str]:
    if not d: return []
    lines = [f"  hostname: {d.get('hostname')}  fqdn: {d.get('fqdn', '')}"]
    for iface in d.get("interfaces", []):
        lines.append(f"  {iface.get('name', '?'):<20} {iface.get('ipv4', '')}")
    return lines


def _fmt_kv_dict(d: dict) -> list[str]:
    """Generic {k: v} formatter used for runtimes / package_managers / browsers."""
    if not d: return []
    return [f"  {k:<12} {v}" for k, v in sorted(d.items())]


def _fmt_displays(d: dict) -> list[str]:
    if not d: return []
    lines = []
    for k, v in d.items():
        if k != "screens": lines.append(f"  {k:<22} {v}")
    for s in d.get("screens", []) or []:
        if isinstance(s, dict):
            parts = [s.get(k) for k in ("output", "geometry", "resolution", "name") if s.get(k)]
            lines.append(f"  screen                 {' · '.join(parts)}")
        else:
            lines.append(f"  screen                 {s}")
    return lines


def _fmt_services(d: dict) -> list[str]:
    if not d: return []
    lines = []
    for k, v in d.items():
        if isinstance(v, list):
            lines.append(f"  {k} ({len(v)}):")
            for item in v: lines.append(f"      - {item}")
        else:
            lines.append(f"  {k}: {v}")
    return lines


def _fmt_python_env(d: dict) -> list[str]:
    if not d: return []
    lines = [f"  Executable: {d.get('executable')}",
             f"  Version   : {d.get('version')} ({d.get('implementation')})",
             f"  In venv   : {d.get('is_venv')}"]
    if d.get("installed_pkgs_count") is not None:
        lines.append(f"  Packages  : {d['installed_pkgs_count']} installed")
    for pkg in (d.get("installed_pkgs_top20") or [])[:20]:
        lines.append(f"    {pkg}")
    return lines


def _fmt_env(d: dict) -> list[str]:
    if not d: return []
    lines = []
    for k, v in sorted(d.items()):
        if k == "PATH_dirs": continue  # too noisy
        if k == "PATH":
            lines.append(f"  PATH                   ({d.get('PATH_entries', '?')} entries; "
                         "expand with 'env' section JSON)")
            continue
        lines.append(f"  {k:<22} {v}")
    return lines


# ---------------------------------------------------------------------
# The registry itself. Order = display order in Doctor / Full Inventory.
# Adding a new probe? Add ONE Section() below and everything downstream
# picks it up: SECTIONS list, text_format section, JS checkbox strip,
# JS Cards mapping (via _hwRender* naming convention).
# ---------------------------------------------------------------------

def build_registry() -> list[Section]:
    """Lazy import so this module has no import cycle with report.py."""
    from arena.inventory.probe_identity import get_identity, get_os
    from arena.inventory.probe_hardware import get_cpu, get_memory, get_gpu, get_motherboard
    from arena.inventory.probe_devices import (
        get_disks, get_storage_devices, get_pci_devices,
        get_usb_devices, get_thermal, get_network, get_displays,
    )
    from arena.inventory.probe_sensors import (
        get_battery, get_fans, get_audio, get_disk_smart, get_thermal_detail,
    )
    from arena.inventory.probe_agent_facts import (
        get_top_processes, get_listening_ports, get_systemd_failed,
        get_boot_time, get_kernel_modules, get_containers,
        get_systemd_timers, get_network_io, get_updates_available,
        get_logged_users, get_cpu_vulnerabilities,
    )
    from arena.inventory.probe_agent_ctx import (
        get_python_venvs, get_git_repos, get_env_secret_names,
        get_crontab_entries,
    )
    from arena.inventory.probe_agent_sys import (
        get_dns_resolvers, get_dmesg_errors, get_journal_errors,
        get_virtualization, get_time_sync, get_firewall_status,
    )
    from arena.inventory.probe_software import (
        get_runtimes, get_package_managers, get_browsers,
        get_env, get_services, get_python_env,
    )

    S = Section
    return [
        # Identity + OS + boot
        S("identity",         "Identity",           "hardware", get_identity,     _fmt_identity),
        S("os",               "Operating System",   "hardware", get_os,           _fmt_os),
        S("boot_time",        "Boot",               "hardware", get_boot_time,    _fmt_boot),
        # Hardware
        S("cpu",              "CPU",                "hardware", get_cpu,          _fmt_cpu),
        S("memory",           "Memory",             "hardware", get_memory,       _fmt_memory),
        S("motherboard",      "Motherboard & BIOS", "hardware", get_motherboard,  _fmt_motherboard),
        S("gpu",              "GPU",                "hardware", get_gpu,          _fmt_gpu),
        S("disks",            "Storage",            "hardware", get_disks,        _fmt_disks),
        S("storage_devices",  "Storage devices",    "hardware", get_storage_devices, None, show_in_doctor=False),
        S("pci_devices",      "PCI devices",        "hardware", get_pci_devices,  None, show_in_doctor=False),
        S("usb_devices",      "USB devices",        "hardware", get_usb_devices,  None, show_in_doctor=False),
        # Sensors
        S("thermal",          "Thermal (legacy)",   "sensors",  get_thermal,        _fmt_thermal, show_in_doctor=False),
        S("thermal_detail",   "Thermal sensors",    "sensors",  get_thermal_detail, _fmt_thermal_detail),
        S("fans",             "Fans",               "sensors",  get_fans,           _fmt_fans),
        S("battery",          "Battery",            "sensors",  get_battery,        _fmt_battery),
        S("audio",            "Audio",              "sensors",  get_audio,          _fmt_audio),
        S("disk_smart",       "Disk SMART",         "sensors",  get_disk_smart,     _fmt_disk_smart),
        # Runtime state
        S("top_processes",    "Top processes",      "agent",    get_top_processes,  _fmt_top_processes),
        S("listening_ports",  "Listening TCP ports","agent",    get_listening_ports,_fmt_listening_ports),
        S("systemd_failed",   "Systemd failed",     "agent",    get_systemd_failed, _fmt_systemd_failed),
        S("kernel_modules",   "Kernel modules",     "agent",    get_kernel_modules, _fmt_kernel_modules),
        S("containers",       "Containers",         "agent",    get_containers,     _fmt_containers),
        S("systemd_timers",   "Systemd timers",     "agent",    get_systemd_timers, _fmt_systemd_timers),
        S("network_io",       "Network I/O",        "agent",    get_network_io,     _fmt_network_io),
        S("updates_available","Package updates",    "agent",    get_updates_available, _fmt_updates),
        S("logged_users",     "Logged-in users",    "agent",    get_logged_users,   _fmt_logged_users),
        S("cpu_vulnerabilities","CPU vulnerabilities","agent",  get_cpu_vulnerabilities, _fmt_cpu_vulns),
        S("virtualization",   "Virtualization",     "agent",    get_virtualization, _fmt_virt),
        S("time_sync",        "Time sync",          "agent",    get_time_sync,      _fmt_time_sync),
        S("firewall_status",  "Firewall",           "agent",    get_firewall_status,_fmt_firewall),
        S("dns_resolvers",    "DNS resolvers",      "agent",    get_dns_resolvers,  _fmt_dns),
        S("env_secret_names", "Env secret names",   "agent",    get_env_secret_names, _fmt_env_secrets),
        S("python_venvs",     "Python venvs",       "agent",    get_python_venvs,   _fmt_python_venvs),
        S("git_repos",        "Git repos",          "agent",    get_git_repos,      _fmt_git_repos),
        S("crontab_entries",  "Crontab",            "agent",    get_crontab_entries,_fmt_crontab),
        S("dmesg_errors",     "Kernel errors",      "agent",    get_dmesg_errors,   _fmt_error_list),
        S("journal_errors",   "Journal errors",     "agent",    get_journal_errors, _fmt_error_list),
        # Software / environment
        S("network",          "Network",            "runtime",  get_network,       _fmt_network),
        S("runtimes",         "Runtimes",           "software", get_runtimes,      _fmt_kv_dict),
        S("package_managers", "Package managers",   "software", get_package_managers, _fmt_kv_dict),
        S("browsers",         "Browsers",           "software", get_browsers,      _fmt_kv_dict),
        S("displays",         "Displays / GUI",     "runtime",  get_displays,      _fmt_displays),
        S("services",         "Services",           "runtime",  get_services,      _fmt_services),
        S("python_env",       "Python environment", "software", get_python_env,    _fmt_python_env, show_in_doctor=False),
        S("env",              "Env (selected)",     "runtime",  get_env,           _fmt_env, show_in_doctor=False),
    ]


REGISTRY: list[Section] = build_registry()


def registry_meta() -> list[dict]:
    """Serializable metadata for the frontend. Loaded via
    ``GET /v1/inventory/registry``. Callables are stripped."""
    return [
        {"name": s.name, "label": s.label, "category": s.category,
         "show_in_doctor": s.show_in_doctor}
        for s in REGISTRY
    ]
