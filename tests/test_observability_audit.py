"""Audit helper tests."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from arena.observability.audit import audit_stats, read_tail, sanitize_audit_event, write_audit_event  # noqa: E402
import unified_bridge as ub  # noqa: E402


def test_sanitize_audit_event_redacts_and_hashes_cmd():
    out = sanitize_audit_event({"token": "secret", "cmd": "echo hi"})
    assert out["token"] == "<redacted>"
    assert out["cmd"] == "echo hi"
    assert out["cmd_len"] == 7
    assert len(out["cmd_sha256"]) == 64


def test_write_tail_and_stats(tmp_path):
    audit_path = tmp_path / "audit.jsonl"
    event = write_audit_event({"type": "unit_test"}, audit_path=audit_path, app_dir=tmp_path, utc_now_fn=lambda: "now")
    assert event["ts"] == "now"
    tail = read_tail(audit_path, 1)
    assert len(tail) == 1
    stats = audit_stats(audit_path)
    assert stats["ok"] is True
    assert stats["total"] == 1
    assert stats["by_type"]["unit_test"] == 1


def test_unified_bridge_audit_reexports():
    assert ub.sanitize_audit_event({"password": "x"})["password"] == "<redacted>"
