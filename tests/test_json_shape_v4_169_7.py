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


# --- v4.169.8: $GITHUB_OUTPUT must receive key=value lines only ------------

def test_github_output_ratchet_is_clean() -> None:
    proc = subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "github_output_ratchet.py")],
        capture_output=True, text=True, timeout=120,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_github_output_ratchet_catches_the_badge_bug(tmp_path: Path) -> None:
    """The exact shape that failed CI on v4.169.6 and v4.169.7."""
    probe = REPO_ROOT / ".github" / "workflows" / "_github_output_probe.yml"
    probe.write_text(
        "name: probe\n"
        "on: workflow_dispatch\n"
        "permissions:\n  contents: read\n"
        "jobs:\n  p:\n    runs-on: ubuntu-latest\n    steps:\n"
        "      - name: bad\n"
        "        run: |\n"
        "          python3 - <<'EOF' >> \"${GITHUB_OUTPUT}\"\n"
        "          print('skip=false')\n"
        "          EOF\n",
        encoding="utf-8",
    )
    try:
        proc = subprocess.run(
            [sys.executable, str(REPO_ROOT / "scripts" / "github_output_ratchet.py")],
            capture_output=True, text=True, timeout=120,
        )
    finally:
        probe.unlink(missing_ok=True)
    assert proc.returncode == 1
    assert "_github_output_probe.yml" in proc.stdout


def test_badge_guard_writes_only_key_value_lines(tmp_path: Path) -> None:
    """Run the badge workflow's own guard logic and inspect what it emits.

    Older version: the annotation went into the output file and GitHub
    rejected it. The step is expected to skip the write AND stay green.
    """
    workflow = (REPO_ROOT / ".github" / "workflows" / "version-badge.yml").read_text(encoding="utf-8")
    start = workflow.index("import json, os, pathlib")
    end = workflow.index("PYEOF", start)
    body = "\n".join(line[10:] if line.startswith(" " * 10) else line
                     for line in workflow[start:end].splitlines())

    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "version.json").write_text('{"semver": "4.169.6"}', encoding="utf-8")
    out = tmp_path / "out.txt"
    out.write_text("", encoding="utf-8")
    script = tmp_path / "guard.py"
    script.write_text(body, encoding="utf-8")

    proc = subprocess.run(
        [sys.executable, str(script)], cwd=tmp_path, capture_output=True, text=True, timeout=60,
        env={"PATH": "/usr/bin:/bin", "VERSION_BARE": "4.169.4", "GITHUB_OUTPUT": str(out)},
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    lines = [ln for ln in out.read_text(encoding="utf-8").splitlines() if ln.strip()]
    assert lines == ["skip=true"], lines
    assert "::warning::" in proc.stdout  # annotation goes to the log, not the file
