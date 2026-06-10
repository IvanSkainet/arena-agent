"""Inventory runner module tests."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from arena.inventory_runner import find_inventory_script, run_inventory  # noqa: E402
from arena.constants import BRIDGE_DIR  # noqa: E402
import unified_bridge as ub  # noqa: E402


def test_find_inventory_script():
    script = find_inventory_script(BRIDGE_DIR)
    assert script is not None
    assert script.name == "inventory.py"


def test_run_inventory_section_json():
    res = run_inventory(bridge_dir=BRIDGE_DIR, section="os", fmt="json", timeout=20)
    assert res["ok"] is True
    assert "inventory" in res
    assert "os" in res["inventory"]


def test_unified_bridge_inventory_wrapper():
    res = ub._inventory_sync(section="os", fmt="json", timeout=20)
    assert res["ok"] is True
    assert "os" in res["inventory"]
