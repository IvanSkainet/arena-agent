"""v4.169.37 -- arena.observability.live_metrics parity tests (mutation-driven).

Comprehensive behavioural tests for live host metrics:
* Constants & initial states;
* `/proc/meminfo` and `/proc/stat` parsing (encoding, field lengths, missing keys);
* `_cpu_percent_fallback` (Linux check, zero deltas, reverse jiffies, empty sample);
* `_collect_cpu` (psutil percpu kwargs, empty per_core -> 0.0, getloadavg exception, Linux fallback, os.cpu_count fallback);
* `_collect_memory` and `_collect_swap` (psutil vs /proc/meminfo fallback, missing MemTotal/SwapTotal, exceptions);
* `_collect_net` and `_collect_disk` (rate calculations, counter wrap / cur < prev -> 0, dt <= 0 -> 0, prev is None -> 0, io is None);
* `_collect_gpu` (2.0s caching window, fresh query);
* `_refresh_totals` (live counter refresh on stale snapshots, exception tolerance);
* `live_metrics_snapshot` (stale path dt < 0.25s, negative dt wall clock backwards, deepcopy isolation, top-level keys).
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import arena.observability.live_metrics as lm  # noqa: E402


@pytest.fixture(autouse=True)
def _reset_lm_state():
    with lm._LOCK:
        lm._LAST_SAMPLE["timestamp"] = None
        lm._LAST_SAMPLE["net_bytes_sent"] = None
        lm._LAST_SAMPLE["net_bytes_recv"] = None
        lm._LAST_SAMPLE["net_packets_sent"] = None
        lm._LAST_SAMPLE["net_packets_recv"] = None
        lm._LAST_SAMPLE["disk_read_bytes"] = None
        lm._LAST_SAMPLE["disk_write_bytes"] = None
        lm._LAST_SAMPLE["disk_read_ops"] = None
        lm._LAST_SAMPLE["disk_write_ops"] = None
        lm._LAST_SAMPLE["gpu_ts"] = None
        lm._LAST_SAMPLE["gpu_devices"] = None
        lm._LAST_SAMPLE["snapshot"] = None
        lm._CPU_STAT_LAST["idle"] = 0
        lm._CPU_STAT_LAST["total"] = 0
    yield
    with lm._LOCK:
        lm._LAST_SAMPLE["timestamp"] = None
        lm._LAST_SAMPLE["net_bytes_sent"] = None
        lm._LAST_SAMPLE["net_bytes_recv"] = None
        lm._LAST_SAMPLE["net_packets_sent"] = None
        lm._LAST_SAMPLE["net_packets_recv"] = None
        lm._LAST_SAMPLE["disk_read_bytes"] = None
        lm._LAST_SAMPLE["disk_write_bytes"] = None
        lm._LAST_SAMPLE["disk_read_ops"] = None
        lm._LAST_SAMPLE["disk_write_ops"] = None
        lm._LAST_SAMPLE["gpu_ts"] = None
        lm._LAST_SAMPLE["gpu_devices"] = None
        lm._LAST_SAMPLE["snapshot"] = None
        lm._CPU_STAT_LAST["idle"] = 0
        lm._CPU_STAT_LAST["total"] = 0


# --------------------------------------------------------------------
# 0. Pinned Constants & Structure
# --------------------------------------------------------------------
def test_constants_pinned():
    assert lm._MIN_SAMPLE_INTERVAL == 0.25


def test_initial_last_sample_keys():
    expected_keys = {
        "timestamp",
        "net_bytes_sent",
        "net_bytes_recv",
        "net_packets_sent",
        "net_packets_recv",
        "disk_read_bytes",
        "disk_write_bytes",
        "disk_read_ops",
        "disk_write_ops",
        "gpu_ts",
        "gpu_devices",
    }
    assert expected_keys.issubset(set(lm._LAST_SAMPLE.keys()))


# --------------------------------------------------------------------
# 1. /proc parsing helpers
# --------------------------------------------------------------------
def test_read_meminfo_kb_success(monkeypatch):
    meminfo_content = "MemTotal:       16384000 kB\nMemFree:         8192000 kB\nMemAvailable:   12000000 kB\nMemTotalExtra:  99999 kB\n"

    class _MockFile:
        def __init__(self, path, encoding=None):
            assert encoding == "ascii"
            self._lines = meminfo_content.splitlines(keepends=True)

        def __iter__(self):
            return iter(self._lines)

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

    monkeypatch.setattr("builtins.open", lambda p, encoding=None: _MockFile(p, encoding=encoding))
    assert lm._read_meminfo_kb("MemTotal") == 16384000
    assert lm._read_meminfo_kb("MemAvailable") == 12000000
    assert lm._read_meminfo_kb("NonExistent") is None


def test_read_meminfo_kb_exception(monkeypatch):
    def _fail_open(*a, **k):
        raise FileNotFoundError("no /proc/meminfo")

    monkeypatch.setattr("builtins.open", _fail_open)
    assert lm._read_meminfo_kb("MemTotal") is None


def test_proc_cpu_stat_5_or_more_fields(monkeypatch):
    class _MockStatFile:
        def __init__(self, path, encoding=None):
            assert encoding == "ascii"

        def readline(self):
            return "cpu  1000 200 300 5000 500 10 20 0 0 0\n"

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

    monkeypatch.setattr("builtins.open", lambda p, encoding=None: _MockStatFile(p, encoding=encoding))
    idle, total = lm._proc_cpu_stat()
    assert idle == 5500  # fields[3] (5000) + fields[4] (500)
    assert total == 7030  # sum of all fields


def test_proc_cpu_stat_exactly_4_fields(monkeypatch):
    class _MockStatFile:
        def readline(self):
            return "cpu  1000 200 300 5000\n"

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

    monkeypatch.setattr("builtins.open", lambda *a, **k: _MockStatFile())
    idle, total = lm._proc_cpu_stat()
    assert idle == 5000  # fields[3] (5000) + 0
    assert total == 6500


def test_proc_cpu_stat_non_cpu_line_and_exception(monkeypatch):
    class _MockStatFile:
        def readline(self):
            return "intr 12345\n"

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

    monkeypatch.setattr("builtins.open", lambda *a, **k: _MockStatFile())
    assert lm._proc_cpu_stat() is None

    monkeypatch.setattr("builtins.open", lambda *a, **k: (_ for _ in ()).throw(OSError("fail")))
    assert lm._proc_cpu_stat() is None


# --------------------------------------------------------------------
# 2. CPU percent fallback (/proc/stat on Linux)
# --------------------------------------------------------------------
def test_cpu_percent_fallback_non_linux(monkeypatch):
    monkeypatch.setattr(lm.platform, "system", lambda: "Windows")
    assert lm._cpu_percent_fallback() is None


def test_cpu_percent_fallback_none_sample(monkeypatch):
    monkeypatch.setattr(lm.platform, "system", lambda: "Linux")
    monkeypatch.setattr(lm, "_proc_cpu_stat", lambda: None)
    assert lm._cpu_percent_fallback() is None


def test_cpu_percent_fallback_linux_deltas(monkeypatch):
    monkeypatch.setattr(lm.platform, "system", lambda: "Linux")
    samples = [
        (5000, 10000),  # init: returns 0.0
        (5200, 11000),  # delta total=1000, delta idle=200 -> busy=800 -> 80.0%
        (5200, 11000),  # zero total delta -> returns 0.0
        (6000, 10500),  # total <= prev_total -> returns 0.0
    ]

    def _mock_stat():
        return samples.pop(0) if samples else None

    monkeypatch.setattr(lm, "_proc_cpu_stat", _mock_stat)

    assert lm._cpu_percent_fallback() == 0.0
    assert lm._cpu_percent_fallback() == 80.0
    assert lm._cpu_percent_fallback() == 0.0
    assert lm._cpu_percent_fallback() == 0.0


def test_cpu_count_fallback(monkeypatch):
    monkeypatch.setattr(os, "cpu_count", lambda: 12)
    assert lm._cpu_count_fallback() == 12

    monkeypatch.setattr(os, "cpu_count", lambda: None)
    assert lm._cpu_count_fallback() == 0


# --------------------------------------------------------------------
# 3. _collect_cpu
# --------------------------------------------------------------------
def test_collect_cpu_psutil_happy_path(monkeypatch):
    mock_psutil = MagicMock()
    mock_psutil.cpu_percent.return_value = [10.0, 20.0, 30.0, 40.0]
    mock_psutil.cpu_count.side_effect = lambda logical: 4 if logical else 2
    mock_psutil.getloadavg.return_value = (0.50, 0.75, 1.25)

    monkeypatch.setattr(lm, "_HAS_PSUTIL", True)
    monkeypatch.setattr(lm, "psutil", mock_psutil)

    res = lm._collect_cpu()
    assert res == {
        "available": True,
        "percent": 25.0,
        "per_core": [10.0, 20.0, 30.0, 40.0],
        "count_logical": 4,
        "count_physical": 2,
        "load_avg_1m": 0.50,
        "load_avg_5m": 0.75,
        "load_avg_15m": 1.25,
    }
    mock_psutil.cpu_percent.assert_called_once_with(interval=None, percpu=True)


def test_collect_cpu_psutil_empty_percore_and_loadavg_exc(monkeypatch):
    mock_psutil = MagicMock()
    mock_psutil.cpu_percent.return_value = []
    mock_psutil.cpu_count.return_value = None
    mock_psutil.getloadavg.side_effect = OSError("no getloadavg on windows")

    monkeypatch.setattr(lm, "_HAS_PSUTIL", True)
    monkeypatch.setattr(lm, "psutil", mock_psutil)

    res = lm._collect_cpu()
    assert res["available"] is True
    assert res["percent"] == 0.0
    assert res["per_core"] == []
    assert res["count_logical"] == 0
    assert res["count_physical"] == 0
    assert res["load_avg_1m"] is None


def test_collect_cpu_psutil_exception_falls_back(monkeypatch):
    mock_psutil = MagicMock()
    mock_psutil.cpu_percent.side_effect = RuntimeError("driver crashed")

    monkeypatch.setattr(lm, "_HAS_PSUTIL", True)
    monkeypatch.setattr(lm, "psutil", mock_psutil)
    monkeypatch.setattr(lm, "_cpu_percent_fallback", lambda: None)

    res = lm._collect_cpu()
    assert res["available"] is False
    assert res["reason"] == "psutil cpu_percent failed: driver crashed"


def test_collect_cpu_fallback_linux(monkeypatch):
    monkeypatch.setattr(lm, "_HAS_PSUTIL", False)
    monkeypatch.setattr(lm, "_cpu_percent_fallback", lambda: 42.5)
    monkeypatch.setattr(lm, "_cpu_count_fallback", lambda: 8)

    res = lm._collect_cpu()
    assert res["available"] is True
    assert res["percent"] == 42.5
    assert res["per_core"] == []
    assert res["count_logical"] == 8
    assert res["count_physical"] == 0


def test_collect_cpu_fallback_unavailable(monkeypatch):
    monkeypatch.setattr(lm, "_HAS_PSUTIL", False)
    monkeypatch.setattr(lm, "_cpu_percent_fallback", lambda: None)

    res = lm._collect_cpu()
    assert res == {
        "available": False,
        "reason": "psutil not installed and /proc/stat unavailable",
    }


# --------------------------------------------------------------------
# 4. _collect_memory and _collect_swap
# --------------------------------------------------------------------
def test_collect_memory_psutil(monkeypatch):
    class _VMem:
        percent = 45.67
        used = 4 * 1024 * 1024 * 1024
        total = 16 * 1024 * 1024 * 1024
        available = 12 * 1024 * 1024 * 1024

    mock_psutil = MagicMock()
    mock_psutil.virtual_memory.return_value = _VMem()
    monkeypatch.setattr(lm, "_HAS_PSUTIL", True)
    monkeypatch.setattr(lm, "psutil", mock_psutil)

    res = lm._collect_memory()
    assert res == {
        "available": True,
        "percent": 45.7,
        "used_bytes": 4 * 1024 * 1024 * 1024,
        "total_bytes": 16 * 1024 * 1024 * 1024,
        "free_bytes": 12 * 1024 * 1024 * 1024,
    }


def test_collect_memory_psutil_exception(monkeypatch):
    mock_psutil = MagicMock()
    mock_psutil.virtual_memory.side_effect = RuntimeError("vmem failed")
    monkeypatch.setattr(lm, "_HAS_PSUTIL", True)
    monkeypatch.setattr(lm, "psutil", mock_psutil)

    res = lm._collect_memory()
    assert res == {"available": False, "reason": "psutil vmem failed: vmem failed"}


def test_collect_memory_fallback_linux(monkeypatch):
    monkeypatch.setattr(lm, "_HAS_PSUTIL", False)
    monkeypatch.setattr(lm.platform, "system", lambda: "Linux")

    def _mock_meminfo(key):
        if key == "MemTotal":
            return 1000000  # ~1GB in kB
        if key == "MemAvailable":
            return 600000   # ~600MB in kB
        return None

    monkeypatch.setattr(lm, "_read_meminfo_kb", _mock_meminfo)
    res = lm._collect_memory()
    assert res == {
        "available": True,
        "percent": 40.0,
        "used_bytes": 400000 * 1024,
        "total_bytes": 1000000 * 1024,
        "free_bytes": 600000 * 1024,
    }


def test_collect_memory_fallback_non_linux(monkeypatch):
    monkeypatch.setattr(lm, "_HAS_PSUTIL", False)
    monkeypatch.setattr(lm.platform, "system", lambda: "Windows")
    assert lm._collect_memory() == {"available": False, "reason": "psutil not installed"}


def test_collect_swap_psutil(monkeypatch):
    class _SMem:
        percent = 10.0
        used = 1024 * 1024
        total = 10 * 1024 * 1024

    mock_psutil = MagicMock()
    mock_psutil.swap_memory.return_value = _SMem()
    monkeypatch.setattr(lm, "_HAS_PSUTIL", True)
    monkeypatch.setattr(lm, "psutil", mock_psutil)

    res = lm._collect_swap()
    assert res == {
        "available": True,
        "percent": 10.0,
        "used_bytes": 1024 * 1024,
        "total_bytes": 10 * 1024 * 1024,
    }


def test_collect_swap_psutil_exception(monkeypatch):
    mock_psutil = MagicMock()
    mock_psutil.swap_memory.side_effect = RuntimeError("swap error")
    monkeypatch.setattr(lm, "_HAS_PSUTIL", True)
    monkeypatch.setattr(lm, "psutil", mock_psutil)

    res = lm._collect_swap()
    assert res == {"available": False, "reason": "psutil swap failed: swap error"}


def test_collect_swap_fallback_linux(monkeypatch):
    monkeypatch.setattr(lm, "_HAS_PSUTIL", False)
    monkeypatch.setattr(lm.platform, "system", lambda: "Linux")

    def _mock_meminfo(key):
        if key == "SwapTotal":
            return 500000
        if key == "SwapFree":
            return 400000
        return None

    monkeypatch.setattr(lm, "_read_meminfo_kb", _mock_meminfo)
    res = lm._collect_swap()
    assert res == {
        "available": True,
        "percent": 20.0,
        "used_bytes": 100000 * 1024,
        "total_bytes": 500000 * 1024,
    }


def test_collect_swap_fallback_non_linux(monkeypatch):
    monkeypatch.setattr(lm, "_HAS_PSUTIL", False)
    monkeypatch.setattr(lm.platform, "system", lambda: "Windows")
    assert lm._collect_swap() == {"available": False, "reason": "psutil not installed"}


# --------------------------------------------------------------------
# 5. _collect_net and _collect_disk rates
# --------------------------------------------------------------------
def test_collect_net_rates(monkeypatch):
    class _NetIO:
        def __init__(self, bs, br, ps, pr):
            self.bytes_sent = bs
            self.bytes_recv = br
            self.packets_sent = ps
            self.packets_recv = pr

    mock_psutil = MagicMock()
    monkeypatch.setattr(lm, "_HAS_PSUTIL", True)
    monkeypatch.setattr(lm, "psutil", mock_psutil)

    # First sample: 1000 sent, 2000 recv
    mock_psutil.net_io_counters.return_value = _NetIO(1000, 2000, 10, 20)
    res1 = lm._collect_net(now=100.0, dt=0.0)
    assert res1["bytes_sent_per_sec"] == 0
    assert res1["bytes_recv_per_sec"] == 0
    assert res1["bytes_sent_total"] == 1000
    assert res1["bytes_recv_total"] == 2000

    # Second sample: dt = 2.0s, +4000 sent, +8000 recv -> 2000 bytes/sec, 4000 bytes/sec
    mock_psutil.net_io_counters.return_value = _NetIO(5000, 10000, 30, 60)
    res2 = lm._collect_net(now=102.0, dt=2.0)
    assert res2["bytes_sent_per_sec"] == 2000
    assert res2["bytes_recv_per_sec"] == 4000
    assert res2["packets_sent_per_sec"] == 10
    assert res2["packets_recv_per_sec"] == 20
    assert res2["bytes_sent_total"] == 5000

    # Counter wrap (cur < prev): rate returns 0
    mock_psutil.net_io_counters.return_value = _NetIO(100, 200, 1, 2)
    res3 = lm._collect_net(now=104.0, dt=2.0)
    assert res3["bytes_sent_per_sec"] == 0


def test_collect_net_no_psutil_or_exception(monkeypatch):
    monkeypatch.setattr(lm, "_HAS_PSUTIL", False)
    assert lm._collect_net(100.0, 1.0) == {"available": False, "reason": "psutil not installed"}

    mock_psutil = MagicMock()
    mock_psutil.net_io_counters.side_effect = RuntimeError("net error")
    monkeypatch.setattr(lm, "_HAS_PSUTIL", True)
    monkeypatch.setattr(lm, "psutil", mock_psutil)
    assert lm._collect_net(100.0, 1.0) == {"available": False, "reason": "psutil net_io failed: net error"}


def test_collect_disk_rates(monkeypatch):
    class _DiskIO:
        def __init__(self, rb, wb, rc, wc):
            self.read_bytes = rb
            self.write_bytes = wb
            self.read_count = rc
            self.write_count = wc

    mock_psutil = MagicMock()
    monkeypatch.setattr(lm, "_HAS_PSUTIL", True)
    monkeypatch.setattr(lm, "psutil", mock_psutil)

    # First sample
    mock_psutil.disk_io_counters.return_value = _DiskIO(1000, 2000, 10, 20)
    res1 = lm._collect_disk(now=100.0, dt=0.0)
    assert res1["read_bytes_per_sec"] == 0
    assert res1["write_bytes_per_sec"] == 0

    # Second sample: dt = 1.0s, +500 read, +1000 write
    mock_psutil.disk_io_counters.return_value = _DiskIO(1500, 3000, 15, 30)
    res2 = lm._collect_disk(now=101.0, dt=1.0)
    assert res2["read_bytes_per_sec"] == 500
    assert res2["write_bytes_per_sec"] == 1000
    assert res2["read_ops_per_sec"] == 5
    assert res2["write_ops_per_sec"] == 10
    assert res2["read_bytes_total"] == 1500


def test_collect_disk_no_counters_or_exception(monkeypatch):
    mock_psutil = MagicMock()
    mock_psutil.disk_io_counters.return_value = None
    monkeypatch.setattr(lm, "_HAS_PSUTIL", True)
    monkeypatch.setattr(lm, "psutil", mock_psutil)
    assert lm._collect_disk(100.0, 1.0) == {"available": False, "reason": "no disk counters"}

    mock_psutil.disk_io_counters.side_effect = RuntimeError("disk error")
    assert lm._collect_disk(100.0, 1.0) == {"available": False, "reason": "psutil disk_io failed: disk error"}


# --------------------------------------------------------------------
# 6. _collect_gpu caching
# --------------------------------------------------------------------
def test_collect_gpu_caches_under_2_seconds(monkeypatch):
    call_count = [0]

    def _mock_query():
        call_count[0] += 1
        return {"available": True, "devices": [{"index": 0, "name": f"GPU_{call_count[0]}"}]}

    monkeypatch.setattr(lm, "_query_gpu_devices", _mock_query)

    gpu1 = lm._collect_gpu(now=100.0)
    assert gpu1["devices"][0]["name"] == "GPU_1"
    assert call_count[0] == 1

    # Call at 101.5s (delta 1.5s < 2.0s) -> returns cached
    gpu2 = lm._collect_gpu(now=101.5)
    assert gpu2["devices"][0]["name"] == "GPU_1"
    assert call_count[0] == 1

    # Call at 102.5s (delta 2.5s >= 2.0s) -> fresh query
    gpu3 = lm._collect_gpu(now=102.5)
    assert gpu3["devices"][0]["name"] == "GPU_2"
    assert call_count[0] == 2


# --------------------------------------------------------------------
# 7. live_metrics_snapshot fresh vs stale lifecycle
# --------------------------------------------------------------------
def test_live_metrics_snapshot_fresh_and_stale(monkeypatch):
    timeline = [100.0, 100.1, 101.0]

    def _fake_time():
        return timeline.pop(0) if timeline else 102.0

    monkeypatch.setattr(lm.time, "time", _fake_time)

    # 1. First snapshot at 100.0s
    snap1 = lm.live_metrics_snapshot()
    assert snap1["ok"] is True
    assert snap1["timestamp"] == 100.0
    assert snap1["stale"] is False
    assert set(snap1.keys()) == {"ok", "timestamp", "stale", "cpu", "memory", "swap", "net", "disk", "gpu"}

    # 2. Second snapshot at 100.1s (dt = 0.1s < _MIN_SAMPLE_INTERVAL 0.25s) -> STALE
    snap2 = lm.live_metrics_snapshot()
    assert snap2["ok"] is True
    assert snap2["timestamp"] == 100.1
    assert snap2["stale"] is True
    assert "re-polled 100.0ms after the previous sample" in snap2["stale_reason"]

    # 3. Third snapshot at 101.0s (dt = 0.9s >= 0.25s) -> FRESH
    snap3 = lm.live_metrics_snapshot()
    assert snap3["ok"] is True
    assert snap3["timestamp"] == 101.0
    assert snap3["stale"] is False


def test_live_metrics_snapshot_negative_dt_clock_step(monkeypatch):
    timeline = [100.0, 95.0]

    def _fake_time():
        return timeline.pop(0) if timeline else 100.0

    monkeypatch.setattr(lm.time, "time", _fake_time)

    snap1 = lm.live_metrics_snapshot()
    assert snap1["stale"] is False

    # Clock jumped backward by 5 seconds
    snap2 = lm.live_metrics_snapshot()
    assert snap2["stale"] is True
    assert "the wall clock moved backwards by 5000.0ms" in snap2["stale_reason"]


def test_live_metrics_snapshot_deepcopy_isolation(monkeypatch):
    snap1 = lm.live_metrics_snapshot()
    # Mutating returned snapshot should not poison internal cache
    if snap1["cpu"]["available"]:
        snap1["cpu"]["percent"] = -999.0

    snap_cached = lm._LAST_SAMPLE["snapshot"]
    if snap_cached["cpu"]["available"]:
        assert snap_cached["cpu"]["percent"] != -999.0
