"""T73: disk cache, kernel single-flight and the actual pipe/exit boundary."""
from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path
from unittest import TestCase

import pytest

from arena.inventory import slow_probe_cache as cache
from arena.inventory.cache_lease import cache_lease

CHECK = TestCase()
ROOT = Path(__file__).resolve().parents[1]


def test_cold_read_only_spawns_a_fixed_worker(tmp_path, monkeypatch):
    monkeypatch.setenv("ARENA_AGENT_HOME", str(tmp_path))
    spawned = []
    monkeypatch.setattr(cache, "_spawn_detached", spawned.append)
    result = cache.cached_python_venvs()
    CHECK.assertEqual(result["cache"]["state"], "pending")
    CHECK.assertEqual(result["venvs"], [])
    CHECK.assertEqual(spawned, [[sys.executable, "-I", str(ROOT / "arena/inventory/cache_worker.py"),
                                 "python_venvs", str(tmp_path / ".inventory-cache")]])


def test_warm_result_is_complete_and_no_worker_starts(tmp_path, monkeypatch):
    monkeypatch.setenv("ARENA_AGENT_HOME", str(tmp_path))
    expected = {"available": True, "repos": [{"path": f"/repo{i}"} for i in range(30)]}
    cache._write("git_repos", tmp_path / ".inventory-cache", expected)
    monkeypatch.setattr(cache, "_spawn_detached", lambda argv: CHECK.fail("fresh cache spawned a scan"))
    result = cache.cached_git_repos()
    CHECK.assertEqual(result["repos"], expected["repos"])
    CHECK.assertEqual(result["cache"]["state"], "ready")


def test_worker_serializes_and_rechecks_freshness(tmp_path):
    runs = []

    def collect():
        runs.append(1)
        return {"available": True, "repos": [{"path": "/full"}]}

    with cache_lease(tmp_path / "git_repos.lease") as held:
        CHECK.assertTrue(held)
        CHECK.assertFalse(cache.refresh_probe("git_repos", tmp_path, collect))
    CHECK.assertTrue(cache.refresh_probe("git_repos", tmp_path, collect))
    CHECK.assertFalse(cache.refresh_probe("git_repos", tmp_path, collect))
    CHECK.assertEqual(runs, [1])
    CHECK.assertEqual(cache._read("git_repos", tmp_path)[0]["repos"], [{"path": "/full"}])


def test_stale_failure_preserves_last_good_data(tmp_path, monkeypatch):
    cache._write("git_repos", tmp_path, {"available": True, "repos": [{"path": "/saved"}]})
    monkeypatch.setattr(cache, "_TTL_SEC", -1)

    def denied():
        raise PermissionError("test denial")

    CHECK.assertTrue(cache.refresh_probe("git_repos", tmp_path, denied))
    result, _ = cache._read("git_repos", tmp_path)
    CHECK.assertEqual(result["repos"], [{"path": "/saved"}])
    CHECK.assertIn("PermissionError", result["error"])


@pytest.mark.parametrize("payload", [b"{", b"[]", b'{"at":"nan","result":{}}',
                                      b'{"at":1,"result":{"repos":"wrong"}}'])
def test_invalid_cache_is_absent_not_a_fake_result(tmp_path, payload):
    (tmp_path / "git_repos.json").write_bytes(payload)
    CHECK.assertEqual(cache._read("git_repos", tmp_path), (None, 0))


def test_unknown_probe_never_becomes_a_path(tmp_path):
    with pytest.raises(ValueError):
        cache._path("../token", tmp_path)


def test_lease_is_released_when_its_process_exits(tmp_path):
    lease = tmp_path / "lease"
    code = ("import sys; from pathlib import Path; "
            "from arena.inventory.cache_lease import cache_lease; "
            "lease=cache_lease(Path(sys.argv[1])); assert lease.__enter__(); "
            "import os; os._exit(0)")
    subprocess.run([sys.executable, "-c", code, str(lease)], cwd=ROOT, check=True, timeout=10)
    with cache_lease(lease) as held:
        CHECK.assertTrue(held)
    CHECK.assertTrue(lease.exists(), "unlinking breaks single-inode lease ownership")


def test_detached_worker_does_not_keep_request_pipes_or_process_alive(tmp_path):
    """An output-only timing assertion misses inherited pipes and CLI exit."""
    release = tmp_path / "release"
    result = tmp_path / "result.json"
    worker = tmp_path / "worker.py"
    worker.write_text(
        "import time\nfrom pathlib import Path\n"
        f"release=Path({str(release)!r})\n"
        "deadline=time.monotonic()+10\n"
        "while not release.exists() and time.monotonic()<deadline: time.sleep(.01)\n"
        f"Path({str(result)!r}).write_text('complete')\n", encoding="utf-8")
    code = ("import sys; from arena.inventory.slow_probe_cache import _spawn_detached; "
            "_spawn_detached([sys.executable, sys.argv[1]]); print('pending', flush=True)")
    try:
        # The worker cannot finish until *after* this subprocess.run returns.
        # A non-daemon refresh, inherited PIPE, or synchronous spawn deadlocks
        # this handshake until the safety timeout, rather than passing by luck.
        out = subprocess.run([sys.executable, "-c", code, str(worker)], cwd=ROOT,
                             capture_output=True, text=True, check=True, timeout=3)
        CHECK.assertEqual(out.stdout.strip(), "pending")
        CHECK.assertFalse(result.exists())
    finally:
        release.touch()
        deadline = time.monotonic() + 10
        while not result.exists() and time.monotonic() < deadline:
            time.sleep(.01)
    CHECK.assertEqual(result.read_text(), "complete")


def test_registry_uses_cached_collectors():
    from arena.inventory.registry import REGISTRY

    collectors = {section.name: section.collector for section in REGISTRY}
    CHECK.assertIs(collectors["python_venvs"], cache.cached_python_venvs)
    CHECK.assertIs(collectors["git_repos"], cache.cached_git_repos)


@pytest.mark.skipif(os.name == "nt", reason="POSIX file-mode semantics")
def test_cache_data_and_lease_are_private(tmp_path):
    directory = tmp_path / "private"
    cache._write("git_repos", directory, {"available": False, "repos": []})
    with cache_lease(directory / "git_repos.lease"):
        CHECK.assertEqual((directory / "git_repos.lease").stat().st_mode & 0o777, 0o600)
    CHECK.assertEqual((directory / "git_repos.json").stat().st_mode & 0o777, 0o600)
    CHECK.assertEqual(directory.stat().st_mode & 0o777, 0o700)
