"""Audit runtime extraction tests."""
import sys
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import unified_bridge as ub  # noqa: E402
from arena.observability.audit_runtime import AuditRuntimeContext, make_audit_runtime  # noqa: E402


def test_unified_audit_runtime_bindings():
    assert ub.sanitize_audit_event.__module__ == "arena.observability.audit_runtime"
    assert ub._load_webhooks.__module__ == "arena.observability.audit_runtime"
    assert ub._save_webhooks.__module__ == "arena.observability.audit_runtime"
    assert ub._fire_webhooks.__module__ == "arena.observability.audit_runtime"
    assert ub.audit.__module__ == "arena.observability.audit_runtime"
    assert ub.read_tail.__module__ == "arena.observability.audit_runtime"


def test_audit_runtime_writes_and_reads_tail(tmp_path):
    with ThreadPoolExecutor(max_workers=1) as executor:
        runtime = make_audit_runtime(AuditRuntimeContext(
            audit_path=tmp_path / "audit.jsonl",
            app_dir=tmp_path,
            webhooks_file=tmp_path / "webhooks.json",
            utc_now=lambda: "now",
            slow_executor=executor,
            log_debug=lambda *args, **kwargs: None,
        ))
        runtime.audit({"type": "unit", "token": "secret"})
        lines = runtime.read_tail(tmp_path / "audit.jsonl", 1)
        assert len(lines) == 1
        assert "unit" in lines[0]
        assert "<redacted>" in lines[0]


def test_audit_runtime_webhooks_load_save(tmp_path):
    with ThreadPoolExecutor(max_workers=1) as executor:
        runtime = make_audit_runtime(AuditRuntimeContext(
            audit_path=tmp_path / "audit.jsonl",
            app_dir=tmp_path,
            webhooks_file=tmp_path / "webhooks.json",
            utc_now=lambda: "now",
            slow_executor=executor,
            log_debug=lambda *args, **kwargs: None,
        ))
        runtime.save_webhooks({"urls": [], "events": ["unit"]})
        assert runtime.load_webhooks()["events"] == ["unit"]
