"""Live host metrics for the Dashboard sparkline charts (v3.95.0).

Produces small JSON snapshots suitable for polling once per second
from the Dashboard and rendering as rolling sparklines. Deliberately
lightweight -- no full hardware probe, no shell-outs on the hot path,
zero external deps required (psutil used when installed for higher
fidelity; falls back to stdlib + /proc parsing on GNU/Linux, and to
"available: false" on other platforms without psutil).

Snapshot shape::

    {
      "ok": true,
      "timestamp": 1721117234.512,   # UNIX seconds, monotonic-ish
      "cpu": {
        "available": true,
        "percent": 12.4,              # aggregate 0..100
        "per_core": [8.3, 15.6, ...], # empty when psutil not installed
        "load_avg_1m": 0.42,          # POSIX-only; null on Windows
        "count_logical": 16,
        "count_physical": 8
      },
      "memory": {
        "available": true,
        "percent": 34.5,
        "used_bytes": 5891842048,
        "total_bytes": 17179869184
      },
      "swap": {
        "available": true,
        "percent": 0.0,
        "used_bytes": 0,
        "total_bytes": 8589934592
      },
      "net": {
        "available": true,
        "bytes_sent_per_sec": 0,      # deltas since prior sample
        "bytes_recv_per_sec": 0,
        "packets_sent_per_sec": 0,
        "packets_recv_per_sec": 0,
        "bytes_sent_total": 12345,
        "bytes_recv_total": 67890
      },
      "disk": {
        "available": true,
        "read_bytes_per_sec": 0,
        "write_bytes_per_sec": 0,
        "read_ops_per_sec": 0,
        "write_ops_per_sec": 0,
        "read_bytes_total": 12345,
        "write_bytes_total": 67890
      },
      "gpu": {
        "available": true,
        "backend": "nvidia-smi" | "rocm-smi" | "none",
        "devices": [
          {"index": 0, "name": "NVIDIA RTX A2000", "gpu_util_percent": 8,
           "mem_used_bytes": 1234567, "mem_total_bytes": 6144000000,
           "temperature_c": 41}
        ]
      }
    }

Cross-platform notes:

* CPU per-core needs psutil.cpu_percent(percpu=True). Without psutil
  we still return an aggregate percent from /proc/stat on GNU/Linux;
  Windows/macOS get {"available": false} with a "reason" field.
* net / disk rates require prior-sample state -- the module keeps a
  process-global _LAST_SAMPLE guarded by a lock so 1Hz callers get
  proper deltas without each having to remember prior state.
* GPU query intentionally best-effort: skipped on this snapshot if
  the last successful GPU probe was <2s ago (queries take ~150ms
  each on nvidia-smi and would dominate a 1Hz budget).
"""
from __future__ import annotations

import platform
import shutil
import subprocess
import threading
import time
from typing import Any

# psutil is optional. We import lazily so the module can still be
# collected even in a minimal install without it.
try:
    import psutil  # type: ignore[import-not-found]
    _HAS_PSUTIL = True
except Exception:  # pragma: no cover - psutil widely available
    psutil = None  # type: ignore[assignment]
    _HAS_PSUTIL = False


_LOCK = threading.Lock()
_LAST_SAMPLE: dict[str, Any] = {
    "timestamp": None,
    "net_bytes_sent": None,
    "net_bytes_recv": None,
    "net_packets_sent": None,
    "net_packets_recv": None,
    "disk_read_bytes": None,
    "disk_write_bytes": None,
    "disk_read_ops": None,
    "disk_write_ops": None,
    "gpu_ts": None,
    "gpu_devices": None,
}

# On the very first cpu_percent() call psutil returns 0.0 because
# it has no prior sample to diff against. Prime it once on import.
if _HAS_PSUTIL:
    try:
        psutil.cpu_percent(interval=None)
    except Exception:
        pass


def _read_meminfo_kb(key: str) -> int | None:
    """Read a single /proc/meminfo entry, in kilobytes."""
    try:
        with open("/proc/meminfo", encoding="ascii") as f:
            for line in f:
                if line.startswith(key + ":"):
                    parts = line.split()
                    return int(parts[1])
    except Exception:
        return None
    return None


def _proc_cpu_stat() -> tuple[int, int] | None:
    """Return (idle, total) jiffies from /proc/stat aggregate line."""
    try:
        with open("/proc/stat", encoding="ascii") as f:
            line = f.readline()
        if not line.startswith("cpu "):
            return None
        fields = [int(x) for x in line.split()[1:]]
        idle = fields[3] + (fields[4] if len(fields) > 4 else 0)
        total = sum(fields)
        return idle, total
    except Exception:
        return None


_CPU_STAT_LAST: dict[str, int] = {"idle": 0, "total": 0}


def _cpu_percent_fallback() -> float | None:
    """GNU/Linux-only CPU% from /proc/stat, computed against the
    prior sample we saved on this module."""
    if platform.system().lower() != "linux":
        return None
    sample = _proc_cpu_stat()
    if not sample:
        return None
    idle, total = sample
    prev_idle = _CPU_STAT_LAST.get("idle") or 0
    prev_total = _CPU_STAT_LAST.get("total") or 0
    _CPU_STAT_LAST["idle"] = idle
    _CPU_STAT_LAST["total"] = total
    if prev_total == 0 or total <= prev_total:
        return 0.0
    dt = total - prev_total
    di = idle - prev_idle
    if dt <= 0:
        return 0.0
    return round((1.0 - di / dt) * 100.0, 1)


def _collect_cpu() -> dict[str, Any]:
    out: dict[str, Any] = {"available": False}
    if _HAS_PSUTIL:
        try:
            per_core = psutil.cpu_percent(interval=None, percpu=True)
            aggregate = round(sum(per_core) / len(per_core), 1) if per_core else 0.0
            out.update({
                "available": True,
                "percent": aggregate,
                "per_core": [round(x, 1) for x in per_core],
                "count_logical": psutil.cpu_count(logical=True) or 0,
                "count_physical": psutil.cpu_count(logical=False) or 0,
            })
            try:
                la1, la5, la15 = psutil.getloadavg()
                out["load_avg_1m"] = round(la1, 2)
                out["load_avg_5m"] = round(la5, 2)
                out["load_avg_15m"] = round(la15, 2)
            except Exception:
                out["load_avg_1m"] = None
            return out
        except Exception as e:
            out["reason"] = f"psutil cpu_percent failed: {e}"
    # Fallback: /proc/stat on GNU/Linux, nothing elsewhere.
    fb = _cpu_percent_fallback()
    if fb is not None:
        try:
            import os as _os
            la1 = _os.getloadavg()[0] if hasattr(_os, "getloadavg") else None
        except Exception:
            la1 = None
        out.update({
            "available": True,
            "percent": fb,
            "per_core": [],
            "count_logical": _cpu_count_fallback(),
            "count_physical": 0,
            "load_avg_1m": round(la1, 2) if la1 is not None else None,
        })
    else:
        out["reason"] = "psutil not installed and /proc/stat unavailable"
    return out


def _cpu_count_fallback() -> int:
    try:
        import os
        return os.cpu_count() or 0
    except Exception:
        return 0


def _collect_memory() -> dict[str, Any]:
    if _HAS_PSUTIL:
        try:
            vm = psutil.virtual_memory()
            return {
                "available": True,
                "percent": round(vm.percent, 1),
                "used_bytes": int(vm.used),
                "total_bytes": int(vm.total),
                "free_bytes": int(vm.available),
            }
        except Exception as e:
            return {"available": False, "reason": f"psutil vmem failed: {e}"}
    if platform.system().lower() == "linux":
        total_kb = _read_meminfo_kb("MemTotal")
        avail_kb = _read_meminfo_kb("MemAvailable")
        if total_kb and avail_kb is not None:
            used_kb = total_kb - avail_kb
            percent = round(used_kb / total_kb * 100.0, 1) if total_kb else 0.0
            return {
                "available": True,
                "percent": percent,
                "used_bytes": used_kb * 1024,
                "total_bytes": total_kb * 1024,
                "free_bytes": avail_kb * 1024,
            }
    return {"available": False, "reason": "psutil not installed"}


def _collect_swap() -> dict[str, Any]:
    if _HAS_PSUTIL:
        try:
            sm = psutil.swap_memory()
            return {
                "available": True,
                "percent": round(sm.percent, 1),
                "used_bytes": int(sm.used),
                "total_bytes": int(sm.total),
            }
        except Exception as e:
            return {"available": False, "reason": f"psutil swap failed: {e}"}
    if platform.system().lower() == "linux":
        total_kb = _read_meminfo_kb("SwapTotal")
        free_kb = _read_meminfo_kb("SwapFree")
        if total_kb is not None:
            used_kb = (total_kb - (free_kb or 0)) if total_kb else 0
            percent = round(used_kb / total_kb * 100.0, 1) if total_kb else 0.0
            return {
                "available": True,
                "percent": percent,
                "used_bytes": used_kb * 1024,
                "total_bytes": total_kb * 1024,
            }
    return {"available": False, "reason": "psutil not installed"}


def _collect_net(now: float, dt: float) -> dict[str, Any]:
    if not _HAS_PSUTIL:
        return {"available": False, "reason": "psutil not installed"}
    try:
        io = psutil.net_io_counters()
    except Exception as e:
        return {"available": False, "reason": f"psutil net_io failed: {e}"}
    prev_sent = _LAST_SAMPLE.get("net_bytes_sent")
    prev_recv = _LAST_SAMPLE.get("net_bytes_recv")
    prev_psent = _LAST_SAMPLE.get("net_packets_sent")
    prev_precv = _LAST_SAMPLE.get("net_packets_recv")
    _LAST_SAMPLE["net_bytes_sent"] = io.bytes_sent
    _LAST_SAMPLE["net_bytes_recv"] = io.bytes_recv
    _LAST_SAMPLE["net_packets_sent"] = io.packets_sent
    _LAST_SAMPLE["net_packets_recv"] = io.packets_recv

    def _rate(cur: int, prev: int | None) -> int:
        if prev is None or dt <= 0 or cur < prev:
            return 0
        return int((cur - prev) / dt)

    return {
        "available": True,
        "bytes_sent_per_sec": _rate(io.bytes_sent, prev_sent),
        "bytes_recv_per_sec": _rate(io.bytes_recv, prev_recv),
        "packets_sent_per_sec": _rate(io.packets_sent, prev_psent),
        "packets_recv_per_sec": _rate(io.packets_recv, prev_precv),
        "bytes_sent_total": int(io.bytes_sent),
        "bytes_recv_total": int(io.bytes_recv),
    }


def _collect_disk(now: float, dt: float) -> dict[str, Any]:
    if not _HAS_PSUTIL:
        return {"available": False, "reason": "psutil not installed"}
    try:
        io = psutil.disk_io_counters()
    except Exception as e:
        return {"available": False, "reason": f"psutil disk_io failed: {e}"}
    if io is None:
        return {"available": False, "reason": "no disk counters"}
    prev_rb = _LAST_SAMPLE.get("disk_read_bytes")
    prev_wb = _LAST_SAMPLE.get("disk_write_bytes")
    prev_ro = _LAST_SAMPLE.get("disk_read_ops")
    prev_wo = _LAST_SAMPLE.get("disk_write_ops")
    _LAST_SAMPLE["disk_read_bytes"] = io.read_bytes
    _LAST_SAMPLE["disk_write_bytes"] = io.write_bytes
    _LAST_SAMPLE["disk_read_ops"] = io.read_count
    _LAST_SAMPLE["disk_write_ops"] = io.write_count

    def _rate(cur: int, prev: int | None) -> int:
        if prev is None or dt <= 0 or cur < prev:
            return 0
        return int((cur - prev) / dt)

    return {
        "available": True,
        "read_bytes_per_sec": _rate(io.read_bytes, prev_rb),
        "write_bytes_per_sec": _rate(io.write_bytes, prev_wb),
        "read_ops_per_sec": _rate(io.read_count, prev_ro),
        "write_ops_per_sec": _rate(io.write_count, prev_wo),
        "read_bytes_total": int(io.read_bytes),
        "write_bytes_total": int(io.write_bytes),
    }


def _collect_gpu(now: float) -> dict[str, Any]:
    """Cache GPU results for 2s -- nvidia-smi/rocm-smi are slow
    and rate-limiting them keeps 1Hz sampling cheap."""
    gpu_ts = _LAST_SAMPLE.get("gpu_ts") or 0.0
    cached = _LAST_SAMPLE.get("gpu_devices")
    if cached is not None and (now - gpu_ts) < 2.0:
        return cached
    fresh = _query_gpu_devices()
    _LAST_SAMPLE["gpu_ts"] = now
    _LAST_SAMPLE["gpu_devices"] = fresh
    return fresh


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
                    parts = [p.strip() for p in line.split(",")]
                    if len(parts) < 6:
                        continue
                    idx, name, util, mem_used, mem_total, temp = parts
                    try:
                        devices.append({
                            "index": int(idx),
                            "name": name,
                            "gpu_util_percent": int(float(util)),
                            "mem_used_bytes": int(float(mem_used) * 1024 * 1024),
                            "mem_total_bytes": int(float(mem_total) * 1024 * 1024),
                            "temperature_c": int(float(temp)),
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


def live_metrics_snapshot() -> dict[str, Any]:
    """Return a single JSON-serialisable snapshot of live host metrics.

    Thread-safe (module-level lock) so multiple pollers all see
    consistent deltas rather than racing on _LAST_SAMPLE."""
    now = time.time()
    with _LOCK:
        prev_ts = _LAST_SAMPLE.get("timestamp")
        dt = (now - prev_ts) if isinstance(prev_ts, (int, float)) else 0.0
        _LAST_SAMPLE["timestamp"] = now

        return {
            "ok": True,
            "timestamp": now,
            "cpu": _collect_cpu(),
            "memory": _collect_memory(),
            "swap": _collect_swap(),
            "net": _collect_net(now, dt),
            "disk": _collect_disk(now, dt),
            "gpu": _collect_gpu(now),
        }
