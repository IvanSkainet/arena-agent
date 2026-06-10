"""Skills registry scanner tests."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from arena.skills.registry import parse_skill_folder, scan_skills  # noqa: E402
import unified_bridge as ub  # noqa: E402


def test_scan_skills_category_and_third_party(tmp_path):
    skills = tmp_path / "skills"
    core = skills / "core" / "health"
    third = skills / "third_party" / "demo"
    core.mkdir(parents=True)
    third.mkdir(parents=True)
    (core / "manifest.json").write_text(json.dumps({"description": "Health", "version": "1"}), encoding="utf-8")
    (third / "SKILL.md").write_text("# Demo\nThird party demo\n", encoding="utf-8")

    res = scan_skills(skills)
    names = {s["name"] for s in res["skills"]}
    assert res["ok"] is True
    assert "core/health" in names
    assert "third_party/demo" in names


def test_parse_skill_folder_manifest(tmp_path):
    skills = tmp_path / "skills"
    d = skills / "web" / "research"
    d.mkdir(parents=True)
    (d / "manifest.json").write_text(json.dumps({"description": "Research", "version": "2"}), encoding="utf-8")
    info = parse_skill_folder(skills, d, category="web")
    assert info["name"] == "web/research"
    assert info["description"] == "Research"
    assert info["version"] == "2"


def test_unified_bridge_skills_wrapper():
    res = ub._skills_list_sync()
    assert res["ok"] is True
    assert isinstance(res["skills"], list)
