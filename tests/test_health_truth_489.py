"""Health must distinguish recovery, unavailable optional tools and real faults."""
from __future__ import annotations

import asyncio
import json
from dataclasses import replace
from types import SimpleNamespace
from unittest import TestCase

from aiohttp import web

from arena.api_v2.info_handlers import make_v2_health_handler
from arena.contexts.core import PublicHandlerContext
from arena.memory.health import memory_status, recovery_record
from arena.memory.schema import init_memory_db
from arena.public.handlers import make_public_handlers
from arena.system.doctor import run_doctor, summarize_checks

CHECK = TestCase()


def test_optional_failure_is_not_counted_as_a_pass():
    result = summarize_checks([{"ok": True}, {"ok": False, "critical": False}])
    CHECK.assertEqual((result["passed"], result["degraded"], result["failed"]), (1, 1, 0))
    CHECK.assertEqual(result["status"], "degraded")
    CHECK.assertTrue(result["ok"])


def test_critical_failure_is_unhealthy():
    result = summarize_checks([{"ok": True}, {"ok": False}])
    CHECK.assertEqual((result["passed"], result["degraded"], result["failed"]), (1, 0, 1))
    CHECK.assertEqual(result["status"], "unhealthy")
    CHECK.assertFalse(result["ok"])


def test_memory_query_failure_is_not_presented_as_zero_facts(tmp_path, monkeypatch):
    monkeypatch.setattr("arena.system.doctor._disk_usage",
                        lambda _: SimpleNamespace(total=100, used=50, free=50))

    def broken():
        raise OSError("storage is offline")

    result = run_doctor(version="test", token="test", bridge_dir=tmp_path, memory_dir=tmp_path,
                        missions_dir=tmp_path, facts_count_fn=broken, internet_check_fn=lambda: True)
    check = next(item for item in result["checks"] if item["name"] == "Memory facts")
    CHECK.assertFalse(check["ok"])
    CHECK.assertIn("storage is offline", check["detail"])
    CHECK.assertFalse(result["ok"])


def test_recovery_remains_visible_after_a_second_start(tmp_path):
    db = tmp_path / "facts.db"
    db.write_bytes(b"not a database")
    CHECK.assertEqual(memory_status(db), "ok")  # presence only, no speculative integrity claim
    init_memory_db(db_path=db, jsonl_path=tmp_path / "facts.jsonl")
    CHECK.assertEqual(memory_status(db), "rebuilt")
    CHECK.assertTrue(recovery_record(db).exists())
    init_memory_db(db_path=db, jsonl_path=tmp_path / "facts.jsonl")
    CHECK.assertEqual(memory_status(db), "rebuilt")
    # Acknowledging the recovery is explicit, not a restart erasing evidence.
    recovery_record(db).unlink()
    CHECK.assertEqual(memory_status(db), "ok")


def test_public_health_reports_rebuilt_without_leaking_the_quarantine_path():
    ctx = PublicHandlerContext(record_request=lambda: None, cors_json_response=web.json_response,
                                metrics={"start_time": 1}, version="test", now=lambda: 2,
                                hostname=lambda: "host", bridge_port=lambda: 1234,
                                memory_status=lambda: "rebuilt")
    response = asyncio.run(make_public_handlers(ctx).health(None))
    result = json.loads(response.text)
    CHECK.assertEqual(result["memory"], "rebuilt")
    CHECK.assertEqual(result["status"], "degraded")
    CHECK.assertNotIn("quarantine", result)
    healthy = asyncio.run(make_public_handlers(replace(ctx, memory_status=lambda: "ok")).health(None))
    CHECK.assertEqual(json.loads(healthy.text)["status"], "healthy")


def _v2(*, watchdog=True, tls_enabled=False, tls_path=""):
    ctx = SimpleNamespace(record_request=lambda: None, cors_json_response=web.json_response,
                           cdp_state={"connected": False}, watchdog_state={"last_check": int(watchdog)},
                           tls_config={"enabled": tls_enabled, "cert_path": tls_path},
                           cluster_config={"enabled": False}, version="test", now=lambda: 2,
                           metrics={"start_time": 1})
    return json.loads(asyncio.run(make_v2_health_handler(ctx)(None)).text)


def test_disabled_optional_services_do_not_make_a_fresh_bridge_unhealthy():
    result = _v2()
    CHECK.assertTrue(result["ok"])
    CHECK.assertEqual(result["status"], "healthy")
    CHECK.assertFalse(result["checks"]["cdp"])
    CHECK.assertFalse(result["checks"]["cluster"])
    CHECK.assertEqual(result["required_checks"], ["bridge", "watchdog"])


def test_watchdog_failure_changes_v2_health():
    result = _v2(watchdog=False)
    CHECK.assertFalse(result["ok"])
    CHECK.assertEqual(result["status"], "unhealthy")


def test_enabled_but_unready_tls_is_not_a_healthy_service():
    result = _v2(tls_enabled=True)
    CHECK.assertFalse(result["ok"])
    CHECK.assertIn("tls", result["required_checks"])


def test_doctor_cli_displays_degradation(monkeypatch, capsys):
    from arena.agentctl_cli import agentctl_system

    monkeypatch.setattr(agentctl_system, "bridge_get", lambda _: {
        "ok": True, "status": "degraded", "passed": 1, "total": 2,
        "degraded": 1, "failed": 0, "checks": []})
    agentctl_system.doctor([])
    text = capsys.readouterr().out
    CHECK.assertIn("1/2 checks passed", text)
    CHECK.assertIn("1 degraded", text)
