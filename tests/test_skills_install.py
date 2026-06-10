"""Third-party skill install/uninstall helper tests."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from arena.skills.install import normalize_third_party_skill_name, uninstall_skill  # noqa: E402
import unified_bridge as ub  # noqa: E402


def test_normalize_third_party_skill_names():
    assert normalize_third_party_skill_name("demo") == ("demo", None)
    assert normalize_third_party_skill_name("third_party/_probe") == ("_probe", None)
    assert normalize_third_party_skill_name("skills/third_party/demo") == ("demo", None)
    assert normalize_third_party_skill_name("core/health")[1]
    assert normalize_third_party_skill_name("../x")[1]


def test_uninstall_skill_removes_only_third_party(tmp_path):
    skills = tmp_path / "skills"
    third = skills / "third_party" / "demo"
    third.mkdir(parents=True)
    res = uninstall_skill("third_party/demo", skills_dir=skills)
    assert res["ok"] is True
    assert not third.exists()


def test_unified_bridge_install_wrappers():
    assert ub._normalize_third_party_skill_name("third_party/demo") == ("demo", None)
