"""Skill runner helper tests."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from arena.skills.runner import run_skill  # noqa: E402
import unified_bridge as ub  # noqa: E402


def test_run_prompt_only_skill(tmp_path):
    skills = tmp_path / "skills"
    skill = skills / "demo"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text("# Demo\nDo demo things\n", encoding="utf-8")
    res = run_skill(
        "demo",
        [],
        skills_dir=skills,
        root_agent=tmp_path,
        bin_dir=tmp_path / "bin",
        subprocess_kwargs_fn=lambda: {},
    )
    assert res["ok"] is True
    assert res["skill_type"] == "prompt"
    assert "Do demo" in res["output"]


def test_unified_bridge_skills_run_wrapper_callable():
    assert callable(ub._skills_run_sync)
