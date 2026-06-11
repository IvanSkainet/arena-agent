"""System sysinfo helper tests."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from arena.system.sysinfo import collect_sysinfo, sysinfo_cim_cpu_counts  # noqa: E402
import unified_bridge as ub  # noqa: E402


def test_collect_sysinfo_basic_shape(tmp_path):
    res = collect_sysinfo(root=tmp_path, clean_platform_name_fn=lambda: "platform-test")
    assert res["ok"] is True
    assert res["os_build"] == "platform-test"
    assert "cpu_cores" in res
    assert "disk_free_gb" in res


def test_unified_bridge_sysinfo_reexports():
    assert ub.collect_sysinfo is collect_sysinfo
    assert ub.sysinfo_cim_cpu_counts is sysinfo_cim_cpu_counts
