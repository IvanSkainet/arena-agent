"""Log cleanup runtime extraction tests."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import unified_bridge as ub  # noqa: E402
from arena.observability.log_cleanup import LogCleanupContext, make_log_cleanup_runtime, rotate_file_if_oversized  # noqa: E402


def test_log_cleanup_factory_outputs(tmp_path):
    runtime = make_log_cleanup_runtime(LogCleanupContext(app_dir=tmp_path, log_files=[]))
    assert callable(runtime.rotate_file_if_oversized)
    assert callable(runtime.rotate_all_logs_on_startup)
    assert callable(runtime.check_disk_space)
    assert callable(runtime.log_cleanup_loop)


def test_unified_log_cleanup_bound_to_module_runtime():
    assert ub._rotate_file_if_oversized.__module__ == "arena.observability.log_cleanup"
    assert ub._rotate_all_logs_on_startup.__module__ == "arena.observability.log_cleanup"
    assert ub._check_disk_space.__module__ == "arena.observability.log_cleanup"
    assert ub._log_cleanup_loop.__module__ == "arena.observability.log_cleanup"


def test_rotate_file_if_oversized_rotates_and_shifts_backups(tmp_path):
    log = tmp_path / "app.log"
    log.write_text("x" * 20, encoding="utf-8")
    Path(f"{log}.1").write_text("old1", encoding="utf-8")
    assert rotate_file_if_oversized(log, max_bytes=10, backups=2) is True
    assert not log.exists()
    assert Path(f"{log}.1").read_text(encoding="utf-8") == "x" * 20
    assert Path(f"{log}.2").read_text(encoding="utf-8") == "old1"


def test_rotate_file_if_oversized_noop_for_small_or_missing(tmp_path):
    missing = tmp_path / "missing.log"
    assert rotate_file_if_oversized(missing, max_bytes=10, backups=2) is False
    small = tmp_path / "small.log"
    small.write_text("small", encoding="utf-8")
    assert rotate_file_if_oversized(small, max_bytes=10, backups=2) is False
    assert small.exists()


def test_rotate_all_logs_on_startup_uses_context_files(tmp_path):
    log = tmp_path / "audit.jsonl"
    log.write_text("x" * 20, encoding="utf-8")
    seen = []
    runtime = make_log_cleanup_runtime(LogCleanupContext(
        app_dir=tmp_path,
        log_files=[log],
        max_log_size=10,
        log_warning=lambda *args: seen.append(args),
    ))
    runtime.rotate_all_logs_on_startup()
    assert Path(f"{log}.1").exists()
    assert seen


def test_check_disk_space_returns_number(tmp_path):
    runtime = make_log_cleanup_runtime(LogCleanupContext(app_dir=tmp_path, log_files=[]))
    pct = runtime.check_disk_space()
    assert isinstance(pct, float | int)
