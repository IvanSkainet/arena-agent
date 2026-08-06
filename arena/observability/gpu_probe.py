"""nvidia-smi / rocm-smi parsing, split out of live_metrics.py.

Moved here in v4.165.0 when the architecture ratchet caught
live_metrics.py crossing the 600-line runtime cap during the #64 fix.
The seam is clean: this module turns vendor CLI text into device dicts
and knows nothing about sampling, caching or rate arithmetic.

The parsing is deliberately forgiving about *fields* and strict about
*devices*. nvidia-smi prints "[N/A]" for values it cannot report --
routine on vGPU and MIG partitions -- and its CSV does not quote the
device name, so a name containing a comma shifts every column. Bug #64
was both of those turning into "you have no GPU" on a machine that
plainly had one. An unreadable field is null; unparseable output still
reports no backend rather than inventing a device.
"""
from __future__ import annotations

import shutil
import subprocess  # nosec B404 -- fixed argv vendor CLIs, no shell
from typing import Any


def _smi_int(text: str) -> int | None:
    """Parse one nvidia-smi numeric field, or None if it is unreadable.

    nvidia-smi writes "[N/A]" (and sometimes "N/A") for values it cannot
    report -- normal on vGPU and MIG partitions. None means "not
    reported"; it must never be silently rendered as 0, which on a
    utilisation gauge reads as a confidently idle GPU.
    """
    try:
        return int(float(text))
    except (TypeError, ValueError):
        return None


def _smi_bytes_from_mib(text: str) -> int | None:
    value = _smi_int(text)
    return None if value is None else value * 1024 * 1024


def _query_gpu_devices() -> dict[str, Any]:
    # Try NVIDIA first.
    if shutil.which("nvidia-smi"):
        try:
            r = subprocess.run(
                [
                    "nvidia-smi",
                    "--query-gpu=index,name,utilization.gpu,memory.used,memory.total,temperature.gpu",
                    "--format=csv,noheader,nounits",
                ],
                capture_output=True, text=True, timeout=3,
            )
            if r.returncode == 0 and r.stdout.strip():
                devices = []
                for line in r.stdout.strip().splitlines():
                    # v4.165.0 (bug #64): a plain `split(",")` broke on a
                    # device name that contains a comma -- nvidia-smi
                    # does not quote the name field, so
                    # "NVIDIA RTX A2000, Laptop" produced seven parts,
                    # shifted every column by one, failed the int() and
                    # dropped the card entirely. The four numeric columns
                    # are fixed and trailing, and the index is fixed and
                    # leading, so split from both ends and let the name
                    # keep whatever is in the middle.
                    raw = line.split(",")
                    if len(raw) < 6:
                        continue
                    idx = raw[0].strip()
                    util, mem_used, mem_total, temp = (p.strip() for p in raw[-4:])
                    name = ",".join(raw[1:-4]).strip()
                    try:
                        devices.append({
                            "index": int(idx),
                            "name": name,
                            # v4.165.0 (bug #64, second half): nvidia-smi
                            # prints "[N/A]" for a field it cannot read --
                            # routine on vGPU and MIG partitions, where
                            # utilisation is simply not exposed. That
                            # raised inside the try and `continue` threw
                            # the WHOLE device away, so a machine with a
                            # working A100 reported backend "none" and an
                            # empty device list: "you have no GPU" instead
                            # of "one field is unavailable". An unreadable
                            # field is now null and the card still shows.
                            "gpu_util_percent": _smi_int(util),
                            "mem_used_bytes": _smi_bytes_from_mib(mem_used),
                            "mem_total_bytes": _smi_bytes_from_mib(mem_total),
                            "temperature_c": _smi_int(temp),
                        })
                    except Exception:
                        continue
                if devices:
                    return {"available": True, "backend": "nvidia-smi", "devices": devices}
        except Exception:
            pass
    # Try AMD ROCm.
    if shutil.which("rocm-smi"):
        try:
            r = subprocess.run(
                ["rocm-smi", "--showuse", "--showtemp", "--showmeminfo", "vram", "--json"],
                capture_output=True, text=True, timeout=3,
            )
            if r.returncode == 0 and r.stdout.strip():
                try:
                    import json
                    data = json.loads(r.stdout)
                except Exception:
                    data = {}
                devices = []
                for key, val in (data.items() if isinstance(data, dict) else []):
                    if not key.startswith("card"):
                        continue
                    if not isinstance(val, dict):
                        continue
                    try:
                        util_raw = val.get("GPU use (%)") or val.get("GPU Use (%)") or "0"
                        util = int(float(str(util_raw).strip().rstrip("%")))
                        vram_used = int(val.get("VRAM Total Used Memory (B)") or 0)
                        vram_total = int(val.get("VRAM Total Memory (B)") or 0)
                        temp_raw = val.get("Temperature (Sensor edge) (C)") or "0"
                        temp = int(float(str(temp_raw).strip()))
                        devices.append({
                            "index": int("".join(c for c in key if c.isdigit()) or 0),
                            "name": val.get("Card series") or val.get("GPU ID") or key,
                            "gpu_util_percent": util,
                            "mem_used_bytes": vram_used,
                            "mem_total_bytes": vram_total,
                            "temperature_c": temp,
                        })
                    except Exception:
                        continue
                if devices:
                    return {"available": True, "backend": "rocm-smi", "devices": devices}
        except Exception:
            pass
    return {"available": False, "backend": "none", "devices": []}


