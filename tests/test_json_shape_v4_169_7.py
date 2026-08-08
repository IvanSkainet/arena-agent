"""v4.169.7 -- a valid JSON scalar must not crash a caller annotated ``-> dict``.

The live bug: ``missions/<name>/mission.json`` containing the four bytes
``null`` is *valid* JSON. ``load_mission_json`` was annotated
``-> dict[str, Any]`` and ended in ``return json.loads(...)``, so it
handed back ``None`` and ``summarize_mission_dir`` died with
``'NoneType' object has no attribute 'get'`` -- taking down the whole
mission listing, not just the one bad mission.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from arena.jsonshape import as_object, loads_array, loads_object
from arena.resources.mission_catalog import load_mission_json, summarize_mission_dir

REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("body", ["null", "5", '"text"', "[1, 2]", "true"])
def test_loads_object_normalises_non_objects(body: str) -> None:
    assert loads_object(body) == {}


def test_loads_object_keeps_objects() -> None:
    assert loads_object('{"a": 1}') == {"a": 1}


def test_loads_object_honours_default() -> None:
    assert loads_object("null", default={"mcpServers": {}}) == {"mcpServers": {}}


def test_loads_object_still_raises_on_malformed() -> None:
    with pytest.raises(json.JSONDecodeError):
        loads_object("{not json")


def test_loads_array_normalises_non_arrays() -> None:
    assert loads_array("null") == []
    assert loads_array('{"a": 1}') == []
    assert loads_array("[1]") == [1]


def test_as_object_does_not_reparse() -> None:
    assert as_object(None) == {}
    assert as_object({"a": 1}) == {"a": 1}


@pytest.mark.parametrize("body", ["null", "[]", '"x"', "0"])
def test_mission_json_scalar_does_not_kill_the_listing(tmp_path: Path, body: str) -> None:
    mission = tmp_path / "m1"
    mission.mkdir()
    (mission / "mission.json").write_text(body, encoding="utf-8")

    assert load_mission_json(mission) == {}
    summary = summarize_mission_dir(mission)  # used to raise AttributeError
    assert summary["name"] == "m1"
    assert summary["state"] == "unknown"


def test_ratchet_is_clean_on_the_current_tree() -> None:
    proc = subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "json_shape_ratchet.py")],
        capture_output=True, text=True, timeout=300,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_ratchet_refuses_to_pass_on_a_truncated_scan(tmp_path: Path) -> None:
    """A gate that scans nothing must fail, not report OK.

    Found by sabotage: misspelling a scan directory left the gate green.
    """
    src = (REPO_ROOT / "scripts" / "json_shape_ratchet.py").read_text(encoding="utf-8")
    probe = REPO_ROOT / "scripts" / "_json_shape_ratchet_probe.py"
    probe.write_text(src.replace('SCAN_DIRS = ("arena", "scripts")', 'SCAN_DIRS = ("scripts",)'),
                     encoding="utf-8")
    try:
        proc = subprocess.run([sys.executable, str(probe)], capture_output=True, text=True, timeout=300)
    finally:
        probe.unlink(missing_ok=True)
    assert proc.returncode == 1
    assert "scanned only" in proc.stdout


def test_ratchet_catches_a_reintroduced_violation(tmp_path: Path) -> None:
    probe = REPO_ROOT / "arena" / "_json_shape_violation_probe.py"
    probe.write_text(
        "from __future__ import annotations\n"
        "import json\n"
        "from typing import Any\n\n"
        "def bad(raw: str) -> dict[str, Any]:\n"
        "    return json.loads(raw)\n",
        encoding="utf-8",
    )
    try:
        proc = subprocess.run(
            [sys.executable, str(REPO_ROOT / "scripts" / "json_shape_ratchet.py")],
            capture_output=True, text=True, timeout=300,
        )
    finally:
        probe.unlink(missing_ok=True)
    assert proc.returncode == 1
    assert "_json_shape_violation_probe.py" in proc.stdout


def test_ratchet_does_not_flag_honest_code() -> None:
    """Reverse sabotage: correct shapes must not trip the gate."""
    probe = REPO_ROOT / "arena" / "_json_shape_ok_probe.py"
    probe.write_text(
        "from __future__ import annotations\n"
        "import json\n"
        "from typing import Any\n\n"
        "def optional(raw: str) -> dict[str, Any] | None:\n"
        "    return json.loads(raw)\n\n"
        "def narrowed(raw: str) -> dict[str, Any]:\n"
        "    data = json.loads(raw)\n"
        "    return data if isinstance(data, dict) else {}\n\n"
        "def untyped(raw):\n"
        "    return json.loads(raw)\n",
        encoding="utf-8",
    )
    try:
        proc = subprocess.run(
            [sys.executable, str(REPO_ROOT / "scripts" / "json_shape_ratchet.py")],
            capture_output=True, text=True, timeout=300,
        )
    finally:
        probe.unlink(missing_ok=True)
    assert proc.returncode == 0, proc.stdout + proc.stderr
