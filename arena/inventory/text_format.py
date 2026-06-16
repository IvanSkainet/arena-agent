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
