"""Arena path layout extraction tests."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import unified_bridge as ub  # noqa: E402
from arena.paths import ArenaPaths  # noqa: E402


def test_arena_paths_from_env_default(monkeypatch, tmp_path):
    monkeypatch.delenv("ARENA_AGENT_HOME", raising=False)
    paths = ArenaPaths.from_env(tmp_path)
    assert paths.root_agent == tmp_path
    assert paths.queue == tmp_path / "queue"
    assert paths.inbox == tmp_path / "queue" / "inbox"
    assert paths.memory_db == tmp_path / "memory" / "facts.db"
    assert paths.webhooks_file == tmp_path / "webhooks.json"


def test_arena_paths_from_env_override(monkeypatch, tmp_path):
    root = tmp_path / "arena-home"
    monkeypatch.setenv("ARENA_AGENT_HOME", str(root))
    paths = ArenaPaths.from_env(tmp_path / "bridge")
    assert paths.root_agent == root
    assert paths.skills_dir == root / "skills"


def test_unified_path_constants_come_from_paths_object():
    assert isinstance(ub.PATHS, ArenaPaths)
    assert ub.ROOT_AGENT == ub.PATHS.root_agent
    assert ub.INBOX == ub.PATHS.inbox
    assert ub.SKILLS_DIR == ub.PATHS.skills_dir
    assert ub.WEBHOOKS_FILE == ub.PATHS.webhooks_file
