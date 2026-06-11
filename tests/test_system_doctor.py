"""Doctor helper tests."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from arena.system.doctor import run_doctor  # noqa: E402
import unified_bridge as ub  # noqa: E402


def test_run_doctor_basic_shape(tmp_path):
    res = run_doctor(
        version="test",
        token="abc",
        bridge_dir=tmp_path,
        memory_dir=tmp_path,
        missions_dir=tmp_path,
        facts_count_fn=lambda: 0,
        internet_check_fn=lambda: True,
        home_dir=tmp_path,
    )
    assert res["ok"] is True
    assert res["total"] >= 8
    names = {c["name"] for c in res["checks"]}
    assert "Bridge running" in names
    assert "Memory facts" in names


def test_unified_bridge_doctor_reexports():
    assert ub.run_doctor is run_doctor
    assert callable(ub._check_internet_sync)
