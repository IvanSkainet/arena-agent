"""Skill runtime compatibility wrapper extraction tests."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import unified_bridge as ub  # noqa: E402
from arena.skills.runtime import SkillRuntimeContext, make_skill_runtime  # noqa: E402


def test_skill_runtime_factory_outputs(tmp_path):
    runtime = make_skill_runtime(SkillRuntimeContext(
        skills_dir=tmp_path / "skills",
        root_agent=tmp_path,
        bin_dir=tmp_path / "bin",
        subprocess_kwargs=lambda: {},
    ))
    assert callable(runtime.skills_list_sync)
    assert callable(runtime.parse_skill_folder_compat)
    assert callable(runtime.skill_install_sync)
    assert callable(runtime.normalize_third_party_skill_name)
    assert callable(runtime.skill_uninstall_sync)
    assert callable(runtime.skills_run_sync)
    assert callable(runtime.skill_path_is_safe)


def test_unified_skill_runtime_bindings():
    assert ub._skills_list_sync.__module__ == "arena.skills.runtime"
    assert ub._parse_skill_folder.__module__ == "arena.skills.runtime"
    assert ub._skill_install_sync.__module__ == "arena.skills.runtime"
    assert ub._normalize_third_party_skill_name.__module__ == "arena.skills.runtime"
    assert ub._skill_uninstall_sync.__module__ == "arena.skills.runtime"
    assert ub._skills_run_sync.__module__ == "arena.skills.runtime"
    assert ub._skill_path_is_safe.__module__ == "arena.skills.runtime"


def test_skill_path_is_safe(tmp_path):
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()
    runtime = make_skill_runtime(SkillRuntimeContext(
        skills_dir=skills_dir,
        root_agent=tmp_path,
        bin_dir=tmp_path / "bin",
        subprocess_kwargs=lambda: {},
    ))
    assert runtime.skill_path_is_safe("demo") is True
    assert runtime.skill_path_is_safe("../outside") is False


def test_normalize_third_party_skill_name_wrapper():
    assert ub._normalize_third_party_skill_name("third_party/demo") == ("demo", None)
