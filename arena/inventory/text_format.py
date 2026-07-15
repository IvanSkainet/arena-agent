"""Human-readable inventory text formatter."""
from __future__ import annotations

from arena.inventory.probe_common import *  # noqa: F401,F403

def format_text(data: dict) -> str:
    lines: list[str] = []
    lines.append("=" * 70)
    lines.append(f"  Arena System Inventory — generated {data.get('generated_at', '')}")
    lines.append("=" * 70)

    if "identity" in data:
        i = data["identity"]
        lines.append("\n### Identity")
        lines.append(f"  User      : {i.get('user', '?')}")
        lines.append(f"  Hostname  : {i.get('hostname', '?')} ({i.get('fqdn', '')})")
        lines.append(f"  Home      : {i.get('home', '')}")
        lines.append(f"  CWD       : {i.get('cwd', '')}")
        lines.append(f"  Shell     : {i.get('shell', '')}")

    if "os" in data:
        o = data["os"]
        lines.append("\n### OS")
        lines.append(f"  System    : {o.get('system')} {o.get('release')} ({o.get('machine')})")
        if o.get("distro"):
            lines.append(f"  Distro    : {o['distro'].get('pretty')}")
        if o.get("caption"):
            lines.append(f"  Edition   : {o['caption']} build {o.get('build_number', '')}")
        if o.get("uptime_seconds"):
            up = o["uptime_seconds"]
            d, r = divmod(up, 86400); h, r = divmod(r, 3600); m, _ = divmod(r, 60)
            lines.append(f"  Uptime    : {d}d {h}h {m}m")
        lines.append(f"  Python    : {o.get('python_version')} ({o.get('python_implementation')})")

    if "cpu" in data:
        c = data["cpu"]
        lines.append("\n### CPU")
        lines.append(f"  Name      : {c.get('name', '?')}")
        lines.append(f"  Cores     : {c.get('cores_physical', '?')} physical, "
                     f"{c.get('cores_logical', '?')} logical")
        if c.get("max_ghz"):
            lines.append(f"  Max Freq  : {c['max_ghz']} GHz")
        if c.get("load_avg"):
            la = c["load_avg"]
            lines.append(f"  Load Avg  : {la[0]:.2f}, {la[1]:.2f}, {la[2]:.2f}")

    if "memory" in data:
        m = data["memory"]
        lines.append("\n### Memory")
        if m.get("total_gb"):
            lines.append(f"  Total     : {m.get('total_gb')} GB")
            if m.get("used_gb") is not None:
                lines.append(f"  Used      : {m.get('used_gb')} GB")
            if m.get("available_gb") is not None:
                lines.append(f"  Available : {m.get('available_gb')} GB")
        if m.get("swap_total_gb"):
            lines.append(f"  Swap      : {m.get('swap_free_gb')} free of {m.get('swap_total_gb')} GB")
        for i, mod in enumerate(m.get("modules", []), 1):
            lines.append(f"  Slot {i}    : {mod.get('size_gb')} GB"
                         + (f" @ {mod['speed_mhz']} MHz" if mod.get('speed_mhz') else "")
                         + (f" — {mod['manufacturer']}" if mod.get('manufacturer') else "")
                         + (f" ({mod['part_number']})" if mod.get('part_number') else ""))

    if "motherboard" in data:
        mb = data["motherboard"]
        if mb.get("motherboard"):
            b = mb["motherboard"]
            lines.append("\n### Motherboard")
            lines.append(f"  Vendor    : {b.get('manufacturer', '')}")
            lines.append(f"  Product   : {b.get('product', '')}")
            if b.get("version"):
                lines.append(f"  Version   : {b['version']}")
        if mb.get("bios"):
            b = mb["bios"]
            lines.append("\n### BIOS")
            lines.append(f"  Vendor    : {b.get('manufacturer', '')}")
            lines.append(f"  Version   : {b.get('version', '')}")
            if b.get("release_date"):
                lines.append(f"  Released  : {b['release_date']}")

    if "gpu" in data and data["gpu"].get("gpus"):
        lines.append("\n### GPU")
        for g in data["gpu"]["gpus"]:
            line = f"  • {g.get('name', '?')}"
            if g.get("vram_mb"):
                line += f" ({g['vram_mb']/1024:.1f} GB VRAM)"
            if g.get("driver_version"):
                line += f" — driver {g['driver_version']}"
            lines.append(line)
        if data["gpu"].get("nvidia"):
            for n in data["gpu"]["nvidia"]:
                lines.append(f"  NVIDIA: {n['name']} — {n['vram_used_mb']}/{n['vram_total_mb']} MB used, "
                             f"{n['temperature_c']}°C, {n['utilization_pct']}% utilization")

    if "disks" in data and data["disks"]:
        lines.append("\n### Disks")
        for d in data["disks"]:
            lines.append(f"  {d['device']:<10} {d.get('mount', ''):<15} "
                         f"{d.get('filesystem', ''):<7} "
                         f"{d['free_gb']:.1f}/{d['total_gb']:.1f} GB free ({d['used_pct']}% used)")

    if "storage_devices" in data and data["storage_devices"]:
        lines.append("\n### Storage devices")
        for d in data["storage_devices"][:12]:
            label = d.get("path") or d.get("name") or d.get("model") or "device"
            size = f" {d.get('size_gb')} GB" if d.get("size_gb") is not None else ""
            model = f" — {d.get('model')}" if d.get("model") else ""
            lines.append(f"  {label:<18} {d.get('type','')}{size}{model}")

    if "pci_devices" in data and data["pci_devices"]:
        lines.append("\n### PCI devices")
        for d in data["pci_devices"][:20]:
            lines.append(f"  [{d.get('category','other')}] {d.get('description') or d.get('name') or ''}")

    if "usb_devices" in data and data["usb_devices"]:
        lines.append("\n### USB devices")
        for d in data["usb_devices"][:20]:
            lines.append(f"  {d.get('id',''):<10} {d.get('name') or d.get('manufacturer') or ''}")

    if "thermal" in data and data["thermal"].get("temperatures"):
        lines.append("\n### Thermal")
        for t in data["thermal"].get("temperatures", [])[:12]:
            lines.append(f"  {t.get('type') or t.get('source')}: {t.get('celsius')}°C")

    if data.get("thermal_detail", {}).get("available"):
        lines.append("\n### Thermal (per-source)")
        by_class: dict[str, list[dict]] = {}
        for s in data["thermal_detail"].get("sensors", []):
            by_class.setdefault(s.get("class", "other"), []).append(s)
        for cls in ("cpu", "gpu", "nvme", "board", "other"):
            for s in by_class.get(cls, []):
                extra = ""
                if s.get("critical_c"):
                    extra = f" (crit {s['critical_c']}°C)"
                elif s.get("high_c"):
                    extra = f" (high {s['high_c']}°C)"
                lines.append(f"  [{cls}] {s.get('label')}: {s.get('celsius')}°C{extra}")

    if data.get("fans", {}).get("available"):
        lines.append("\n### Fans")
        for f in data["fans"].get("fans", []):
            lines.append(f"  {f.get('label')}: {f.get('rpm')} RPM")

    if data.get("battery", {}).get("available"):
        b = data["battery"]
        lines.append("\n### Battery")
        if b.get("percent") is not None:
            lines.append(f"  Charge    : {b['percent']}% "
                         f"({'AC' if b.get('plugged') else 'discharging'})")
        for bat in b.get("batteries", []):
            parts = []
            if bat.get("manufacturer"): parts.append(bat["manufacturer"])
            if bat.get("model_name"):   parts.append(bat["model_name"])
            if bat.get("technology"):   parts.append(bat["technology"])
            if parts:
                lines.append(f"  Device    : {' / '.join(parts)}")
            if bat.get("health_pct") is not None:
                lines.append(f"  Health    : {bat['health_pct']}% "
                             f"(full {bat.get('energy_full')} of "
                             f"design {bat.get('energy_full_design')})")
            if bat.get("cycle_count") is not None:
                lines.append(f"  Cycles    : {bat['cycle_count']}")

    if data.get("disk_smart", {}).get("available"):
        lines.append("\n### Disk SMART")
        for d in data["disk_smart"].get("devices", []):
            status = "PASS" if d.get("passed") else "FAIL" if d.get("passed") is False else "?"
            head = f"  {d.get('device')} [{status}] {d.get('model') or ''}"
            lines.append(head)
            details = []
            if d.get("temperature_c") is not None:
                details.append(f"temp {d['temperature_c']}°C")
            if d.get("power_on_hours") is not None:
                details.append(f"{d['power_on_hours']} h powered on")
            if d.get("percent_used") is not None:
                details.append(f"{d['percent_used']}% used (NVMe)")
            if d.get("available_spare_pct") is not None:
                details.append(f"{d['available_spare_pct']}% spare")
            if d.get("reallocated_sectors") is not None:
                details.append(f"{d['reallocated_sectors']} reallocated")
            if details:
                lines.append(f"    {' · '.join(details)}")

    if data.get("audio", {}).get("available"):
        a = data["audio"]
        lines.append("\n### Audio")
        for s in a.get("sinks", [])[:10]:
            lines.append(f"  out: {s.get('name', '')}")
        for s in a.get("sources", [])[:10]:
            lines.append(f"  in : {s.get('name', '')}")

    if data.get("top_processes", {}).get("available"):
        tp = data["top_processes"]
        lines.append("\n### Top processes")
        for p in tp.get("by_cpu", [])[:5]:
            lines.append(f"  cpu {p['cpu_pct']:>5.1f}% · {p['rss_mb']:>7.1f} MB · "
                         f"{p['name']} (pid {p['pid']})")
        for p in tp.get("by_memory", [])[:5]:
            lines.append(f"  ram {p['rss_mb']:>7.1f} MB · {p['cpu_pct']:>5.1f}% · "
                         f"{p['name']} (pid {p['pid']})")

    if data.get("listening_ports", {}).get("available"):
        lp = data["listening_ports"]
        lines.append(f"\n### Listening TCP ports ({len(lp.get('tcp', []))})")
        for p in lp.get("tcp", [])[:25]:
            lines.append(f"  tcp/{p['port']:<6} {p.get('process', ''):<20} "
                         f"pid {p.get('pid', '?')}  {p.get('addr', '')}")

    if data.get("systemd_failed", {}).get("available"):
        sf = data["systemd_failed"]
        failed = (sf.get("system_failed") or []) + (sf.get("user_failed") or [])
        if failed:
            lines.append(f"\n### Systemd failed units ({len(failed)})")
            for u in failed[:20]:
                lines.append(f"  {u['unit']} — {u.get('description', '')}")

    if data.get("boot_time", {}).get("available"):
        b = data["boot_time"]
        up = b.get("uptime_seconds", 0)
        d, r = divmod(up, 86400); h, r = divmod(r, 3600); m, _ = divmod(r, 60)
        lines.append("\n### Boot")
        lines.append(f"  Booted   : {b.get('boot_time_iso', '')}")
        lines.append(f"  Uptime   : {d}d {h}h {m}m")

    if data.get("kernel_modules", {}).get("available"):
        km = data["kernel_modules"]
        lines.append(f"\n### Kernel modules ({km.get('count', 0)} loaded, "
                     f"showing top {len(km.get('modules', []))})")
        for mod in km.get("modules", [])[:15]:
            lines.append(f"  {mod['name']:<28} {mod['size_bytes']:>10} B  "
                         f"used by {mod['used_count']}")

    if data.get("containers", {}).get("available"):
        c = data["containers"]
        lines.append(f"\n### Containers ({c.get('runtime', '?')}, "
                     f"{c.get('running_count', 0)}/{c.get('total_count', 0)} running)")
        for x in c.get("containers", [])[:15]:
            lines.append(f"  {(x.get('name') or '?'):<30} {x.get('status', '')}")
            if x.get("image"):
                lines.append(f"    image : {x['image']}")
            if x.get("ports"):
                lines.append(f"    ports : {x['ports'][:100]}")

    if data.get("systemd_timers", {}).get("available"):
        t = data["systemd_timers"]
        lines.append(f"\n### Systemd timers ({len(t.get('timers', []))})")
        for tm in t.get("timers", [])[:15]:
            nxt = tm.get("next") or "—"
            lines.append(f"  {(tm.get('unit') or '?'):<40} next: {nxt}")

    if data.get("network_io", {}).get("available"):
        nio = data["network_io"]
        lines.append("\n### Network I/O (cumulative)")
        for i in nio.get("interfaces", []):
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

    if data.get("updates_available", {}).get("available"):
        u = data["updates_available"]
        lines.append(f"\n### Package updates available ({u.get('manager', '?')})")
        pc = u.get("pending_count")
        lines.append(f"  Pending  : {pc if pc is not None else '?'}")
        if u.get("checked_at"):
            lines.append(f"  Checked  : {u['checked_at']}")
        for pkg in u.get("sample", [])[:8]:
            if pkg.get("new_version"):
                lines.append(f"    {pkg['name']:<28} -> {pkg['new_version']}")
            else:
                lines.append(f"    {pkg['name']}")

    if data.get("logged_users", {}).get("available"):
        lu = data["logged_users"]
        lines.append(f"\n### Logged-in users ({len(lu.get('users', []))})")
        for user in lu.get("users", []):
            parts = [user.get("terminal") or ""]
            if user.get("host"): parts.append(f"from {user['host']}")
            if user.get("started"): parts.append(user["started"])
            lines.append(f"  {(user.get('name') or '?'):<12} {'  '.join(p for p in parts if p)}")

    if data.get("cpu_vulnerabilities", {}).get("available"):
        v = data["cpu_vulnerabilities"]
        mits = v.get("mitigations") or {}
        lines.append(f"\n### CPU vulnerabilities ({len(mits)})")
        for name, status in mits.items():
            short = str(status).split(";")[0].strip()
            lines.append(f"  {name:<20} {short}")

    if "network" in data:
        n = data["network"]
        lines.append("\n### Network")
        lines.append(f"  Hostname  : {n.get('hostname')} ({n.get('fqdn')})")
        for iface in n.get("interfaces", []):
            lines.append(f"  {iface.get('name', '?'):<20} {iface.get('ipv4', '')}")

    if "runtimes" in data and data["runtimes"]:
        lines.append("\n### Runtimes")
        for name, v in sorted(data["runtimes"].items()):
            lines.append(f"  {name:<12} {v}")

    if "package_managers" in data and data["package_managers"]:
        lines.append("\n### Package managers / containers")
        for name, v in sorted(data["package_managers"].items()):
            lines.append(f"  {name:<12} {v}")

    if "browsers" in data and data["browsers"]:
        lines.append("\n### Browsers")
        for name, v in sorted(data["browsers"].items()):
            lines.append(f"  {name:<20} {v}")

    if "displays" in data and data["displays"]:
        lines.append("\n### Display / GUI")
        d = data["displays"]
        for k, v in d.items():
            if k != "screens":
                lines.append(f"  {k:<22} {v}")
        for s in d.get("screens", []) or []:
            lines.append(f"  screen                 {s}")

    if "services" in data and data["services"]:
        lines.append("\n### Services")
        for k, v in data["services"].items():
            if isinstance(v, list):
                lines.append(f"  {k} ({len(v)}):")
                for item in v[:10]:
                    lines.append(f"      - {item}")
                if len(v) > 10:
                    lines.append(f"      ... and {len(v) - 10} more")
            else:
                lines.append(f"  {k}: {v}")

    if "python_env" in data:
        pe = data["python_env"]
        lines.append("\n### Python environment")
        lines.append(f"  Executable: {pe.get('executable')}")
        lines.append(f"  Version   : {pe.get('version')} ({pe.get('implementation')})")
        lines.append(f"  In venv   : {pe.get('is_venv')}")
        if pe.get("installed_pkgs_count") is not None:
            lines.append(f"  Packages  : {pe['installed_pkgs_count']} installed")

    if "env" in data:
        e = data["env"]
        lines.append("\n### Environment (selected)")
        for k in sorted(e.keys()):
            if k in ("PATH_dirs", "PATH"):
                continue
            v = e[k]
            if isinstance(v, str) and len(v) > 100:
                v = v[:100] + "..."
            lines.append(f"  {k:<22} {v}")
        if "PATH_entries" in e:
            lines.append(f"  PATH                   ({e['PATH_entries']} entries)")

    lines.append("\n" + "=" * 70)
    return "\n".join(lines)
