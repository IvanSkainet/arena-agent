"""v4.61.1 fix: graceful sqlite cleanup on Windows.

The original fixture only called ``gc.collect()`` AFTER the
``yield``. On Windows, sqlite3 holds an exclusive file lock on
``facts.db`` that survives until Python's GC finalises the
connection objects. Because the test body uses
``with sqlite3.connect(...) as conn:`` which closes the
connection on block exit, the file is normally released too,
but if pytest fixture finalisation runs the ``gc.collect()``
*before* the ``__exit__`` of the inner ``with`` (which is
order-dependent and platform-dependent), the connection is
still alive when the test's tempdir is removed. The Windows
file lock then blocks the rmtree and pytest reports it as
``PermissionError: [WinError 32]``.

Fix: run ``gc.collect()`` *before* the test body starts
(pre-yield), so any sqlite connection objects left over from
a prior test are finalised before the new tempdir is touched.
Also pre-create the memory/ subdirectory so the
``temp_arena_home / "memory" / "facts.db"`` path is owned by
the fixture, not by the test.

Live-failed: v4.61.0 CI run id 30034756453 / 30035666162.
"""
import os
import sys
import json
import sqlite3
import tempfile
import zipfile
import shutil
import gc
from pathlib import Path
import pytest

# Add repository root to system path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.memory import append as memory_append
from bin.memory_recall import recall_facts, score as recall_score
from scripts.hwinfo_lite import collect_all as hwinfo_collect


@pytest.fixture
def temp_arena_home():
    """Setup a clean temporary arena agent home for testing.

    v4.61.1: collect any leftover sqlite Connection objects BEFORE
    the tempdir is created, so a stale handle from the prior test
    cannot lock ``facts.db`` on Windows. Then create the
    memory/ subdirectory up front (test_sqlite_memory_db_and_cli_sync
    relies on it being a valid empty directory before
    ``memory_append`` is called).
    """
    gc.collect()  # pre-yield: free any stale sqlite connections
    with tempfile.TemporaryDirectory() as tmpdir:
        old_env = os.environ.get("ARENA_AGENT_HOME")
        os.environ["ARENA_AGENT_HOME"] = tmpdir
        # Pre-create the memory/ subdirectory so the fixture owns
        # its creation (matches the production layout).
        (Path(tmpdir) / "memory").mkdir(parents=True, exist_ok=True)
        try:
            yield Path(tmpdir)
        finally:
            # Close any connections the test body left dangling,
            # then collect, then let the tempdir cleanup run.
            gc.collect()
            if old_env is not None:
                os.environ["ARENA_AGENT_HOME"] = old_env
            else:
                os.environ.pop("ARENA_AGENT_HOME", None)


def test_sqlite_memory_db_and_cli_sync(temp_arena_home):
    """Test that SQLite DB is correctly created, facts can be stored and retrieved both via code and CLI."""
    db_path = temp_arena_home / "memory" / "facts.db"

    # Verify no database exists initially
    assert not db_path.exists()

    # Store a fact using memory CLI append
    fact_data = {
        "ts": "2026-06-05T12:00:00Z",
        "key": "test_key",
        "value": "This is a super secret message for testing memory FTS5 and trigrams",
        "tags": ["secret", "test"]
    }
    memory_append(fact_data)

    # Database and tables must be created automatically
    assert db_path.exists()

    # Query database directly to check layout and triggers.
    # v4.61.1: explicit conn.close() (no `with`) so the file lock
    # is released before the test returns, regardless of platform
    # finalisation order.
    conn = sqlite3.connect(db_path)
    try:
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM memory_facts WHERE key = ?", ("test_key",)).fetchone()
        assert row is not None
        assert row["value"] == fact_data["value"]
        assert "secret" in row["tags"]

        # Verify FTS5 virtual table works and trigger indexed it
        fts_row = conn.execute("SELECT * FROM memory_fts WHERE memory_fts MATCH 'secret'").fetchone()
        assert fts_row is not None
        assert fts_row["key"] == "test_key"
    finally:
        conn.close()


def test_memory_recall_scoring_and_tf(temp_arena_home):
    """Test that TF scoring algorithm in bin/memory_recall.py functions perfectly on database facts."""
    fact_1 = {
        "ts": "2026-06-05T12:00:00Z",
        "key": "mamba",
        "value": "Mamba is a fast hardware acceleration protocol for AI and LLMs.",
        "tags": ["hardware", "mamba"]
    }
    fact_2 = {
        "ts": "2026-06-05T12:01:00Z",
        "key": "cobra",
        "value": "Cobra is a completely different project, python terminal cmd library.",
        "tags": ["terminal", "cobra"]
    }

    memory_append(fact_1)
    memory_append(fact_2)

    # Recall with key tokens
    tokens = ["mamba", "acceleration"]
    facts = recall_facts(tokens, top=5)

    assert len(facts) >= 1
    best_fact = json.loads(facts[0]["text"])
    assert best_fact["key"] == "mamba"
    assert facts[0]["score"] >= 2  # Matches mamba and acceleration


def test_hwinfo_lite_execution():
    """Verify that hwinfo_lite.py runs cleanly on the current platform and returns proper JSON structure."""
    info = hwinfo_collect()
    assert isinstance(info, dict)
    assert "os" in info
    assert "cpu" in info
    assert "gpu" in info
    assert "ram" in info
    assert "storage" in info
    assert "network" in info


def test_skill_install_zip_unpack_with_junk_and_nesting(temp_arena_home):
    """Test the enhanced ZIP plugin extraction logic: verify it handles junk files, __MACOSX, and correct un-nesting."""
    from unified_bridge import _skill_install_sync

    # Temporarily override SKILLS_DIR in unified_bridge to point inside our temp directory
    import unified_bridge
    old_skills_dir = unified_bridge.SKILLS_DIR
    unified_bridge.SKILLS_DIR = temp_arena_home / "skills"

    try:
        # Create a dummy ZIP file with nested structure + __MACOSX junk
        zip_path = temp_arena_home / "test_plugin.zip"
        with zipfile.ZipFile(zip_path, 'w') as z:
            # Nested root folder
            z.writestr("test_plugin-master/run.py", "print('hello')")
            z.writestr("test_plugin-master/SKILL.md", "# Test Plugin")
            # Junk macOS folders/files
            z.writestr("__MACOSX/test_plugin-master/._run.py", "")
            z.writestr("test_plugin-master/.DS_Store", "")

        # Call installation sync
        res = _skill_install_sync("test_plugin", str(zip_path))

        assert res["ok"] is True
        target_path = Path(res["path"])

        # Verify that it was successfully un-nested:
        # test_plugin-master files should be directly in skills/third_party/test_plugin/
        assert (target_path / "run.py").exists()
        assert (target_path / "SKILL.md").exists()
        assert not (target_path / "test_plugin-master").exists()
        assert not (target_path / "__MACOSX").exists()

    finally:
        unified_bridge.SKILLS_DIR = old_skills_dir


def test_skill_install_git_injection_handling(temp_arena_home):
    """Verify that git clone command in skill install handles flag injections safely."""
    from unified_bridge import _skill_install_sync

    # Try an injection-style URL
    res = _skill_install_sync("dangerous_skill", "--upload-pack=touch_injected")
    assert res["ok"] is False
