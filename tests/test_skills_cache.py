"""Skills cache tests."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from arena.skills.cache import SkillsCache  # noqa: E402


def test_skills_cache_caches_and_resets(tmp_path):
    calls = {"n": 0}
    def scan():
        calls["n"] += 1
        return {"ok": True, "skills": [{"name": "demo"}], "count": 1}
    cache = SkillsCache(skills_dir=tmp_path, scan_fn=scan, ttl=60, hot_reload=False)
    assert cache.list()["cached"] is False
    assert cache.list()["cached"] is True
    assert calls["n"] == 1
    cache.reset()
    assert cache.list()["cached"] is False
    assert calls["n"] == 2
