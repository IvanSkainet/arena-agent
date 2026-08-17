"""System handler factory smoke tests."""
import asyncio
import json
import sys
from pathlib import Path
from unittest.mock import patch

from aiohttp.test_utils import make_mocked_request

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import unified_bridge as ub  # noqa: E402
from arena.handler_context import SystemHandlerContext  # noqa: E402
from arena.system.handlers import make_system_handlers  # noqa: E402


def test_system_handlers_factory_outputs():
    ctx = SystemHandlerContext(
        require_auth=ub.require_auth,
        record_request=ub._record_request,
        cors_json_response=ub._cors_json_response,
        executor=ub._EXECUTOR,
        common_status=ub.common_status,
        version=ub.VERSION,
        clean_platform_name=ub.get_clean_platform_name,
        doctor_sync=lambda token: {"ok": True, "passed": 1, "total": 1, "checks": []},
        sysinfo_sync=lambda root: {"ok": True, "root": str(root)},
        play_beep_sync=lambda beep_type, freq, dur: {"ok": True, "type": beep_type, "frequency": freq, "duration": dur},
        send_notification_sync=lambda title, msg: {"ok": True, "title": title, "message": msg},
    )
    handlers = make_system_handlers(ctx)
    assert callable(handlers.version)
    assert callable(handlers.info)
    assert callable(handlers.status)
    assert callable(handlers.config)


def test_version_uses_configured_install_root_and_public_provenance_allowlist(tmp_path):
    from arena.admin.deployment_provenance import (
        DEPLOYED_PROVENANCE,
        build_deployed_provenance,
        write_deployed_provenance,
    )

    release = {
        "schemaVersion": 1,
        "repository": "IvanSkainet/arena-agent",
        "sourceCommit": "a" * 40,
        "releaseTag": "v4.170.0",
        "candidateRunId": "123",
    }
    deployed = build_deployed_provenance(
        release=release, tag="v4.170.0", downloaded_sha256="b" * 64,
        expected_sha256="b" * 64, authenticated=True, previous=None,
        installed_at="2026-08-17T10:00:00Z",
    )
    write_deployed_provenance(tmp_path / DEPLOYED_PROVENANCE, deployed)
    ctx = SystemHandlerContext(
        require_auth=ub.require_auth,
        record_request=lambda: None,
        cors_json_response=ub._cors_json_response,
        executor=ub._EXECUTOR,
        common_status=ub.common_status,
        version=ub.VERSION,
        clean_platform_name=ub.get_clean_platform_name,
        doctor_sync=lambda token: {},
        sysinfo_sync=lambda root: {},
        play_beep_sync=lambda beep_type, freq, dur: {},
        send_notification_sync=lambda title, msg: {},
    )
    handlers = make_system_handlers(ctx)
    app = ub.make_app({"token": "test", "bind": "127.0.0.1", "root": str(tmp_path)})
    request = make_mocked_request("GET", "/v1/version", app=app)
    with patch("arena.admin.auto_update._install_root", return_value=tmp_path):
        response = asyncio.run(handlers.version(request))
    body = json.loads(response.text)
    assert body["deployment"] == {
        "deploymentModel": "archive",
        "sourceCommit": "a" * 40,
        "releaseTag": "v4.170.0",
        "candidateRunId": "123",
        "zipSha256": "b" * 64,
        "installedAt": "2026-08-17T10:00:00Z",
        "authenticated": True,
    }
    assert "previousDeployment" not in body["deployment"]
    assert "rollback" not in body["deployment"]


def test_unified_routes_use_extracted_system_handlers():
    app = ub.make_app({"token": "test", "profile": "owner-shell", "root": "/tmp", "active_exec": 0, "max_concurrent": 3, "audit": "audit"})
    paths = {(r.method, r.resource.get_info().get("path") or r.resource.get_info().get("formatter")) for r in app.router.routes()}
    for path in ["/v1/version", "/v1/info", "/v1/status", "/v1/config", "/v1/doctor", "/v1/sysinfo"]:
        assert ("GET", path) in paths
    assert ("POST", "/v1/beep") in paths
