"""
Tests for ``tests/_stub_bridge.py`` (#185).

Guards the shared test HTTP server contract:
* Ephemeral port binding on port 0 (#175)
* Health endpoint handling
* Agent config endpoint handling and failure simulation
* Route table response injection (GET/POST)
* Request tracking and payload recording
* Path query string stripping
* Context manager lifecycle
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any

import pytest

from tests._stub_bridge import StubBridge, _StubBridge


def _get(url: str) -> tuple[int, dict[str, Any]]:
    if not url.startswith(("http://", "https://")):
        raise ValueError(f"Unsupported scheme: {url}")
    req = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:  # noqa: S310  # nosec B310
            data = json.loads(resp.read().decode("utf-8"))
            return resp.status, data
    except urllib.error.HTTPError as e:
        data = json.loads(e.read().decode("utf-8"))
        return e.code, data


def _post(url: str, body: dict[str, Any] | bytes) -> tuple[int, dict[str, Any]]:
    if not url.startswith(("http://", "https://")):
        raise ValueError(f"Unsupported scheme: {url}")
    if isinstance(body, bytes):
        payload = body
    else:
        payload = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:  # noqa: S310  # nosec B310
            data = json.loads(resp.read().decode("utf-8"))
            return resp.status, data
    except urllib.error.HTTPError as e:
        data = json.loads(e.read().decode("utf-8"))
        return e.code, data


def test_alias_parity():
    assert _StubBridge is StubBridge


def test_ephemeral_port_binds_to_nonzero_port():
    stub = StubBridge().start()
    try:
        assert stub.port > 0
        assert stub.url() == f"http://127.0.0.1:{stub.port}"
    finally:
        stub.stop()


def test_context_manager_lifecycle():
    with StubBridge() as stub:
        status, body = _get(f"{stub.url()}/health")
        assert status == 200
        assert body["ok"] is True
        assert body["service"] == "stub"
    # After exiting context, server is stopped and connection fails
    with pytest.raises((urllib.error.URLError, ConnectionRefusedError, OSError)):
        _get(f"{stub.url()}/health")


def test_health_status_healthy_and_sick():
    with StubBridge(health_status=200) as stub:
        status, body = _get(f"{stub.url()}/health")
        assert status == 200
        assert body["ok"] is True
        assert body["version"] == "test"

    with StubBridge(health_status=503) as sick_stub:
        status, body = _get(f"{sick_stub.url()}/health")
        assert status == 503
        assert body["ok"] is False
        assert body["error"] == "sick"


def test_agent_config_endpoint_handling():
    # When agent_config is None and not in responses, returns 200 with empty dict
    with StubBridge() as stub_empty:
        status, body = _get(f"{stub_empty.url()}/v1/agent/config")
        assert status == 200
        assert body == {}

    cfg = {"ok": True, "version": "v1.2.3", "urls": ["http://a", "http://b"]}
    with StubBridge(agent_config=cfg) as stub:
        status, body = _get(f"{stub.url()}/v1/agent/config")
        assert status == 200
        assert body == cfg

    # config_status non-200 simulates bridge sick on config
    with StubBridge(agent_config=cfg, config_status=500) as sick_stub:
        status, body = _get(f"{sick_stub.url()}/v1/agent/config")
        assert status == 500
        assert body["ok"] is False


def test_custom_routes_and_query_stripping():
    responses = {
        ("GET", "/test/item"): (200, {"name": "sample"}),
        ("POST", "/test/submit"): (201, {"accepted": True}),
    }
    with StubBridge(responses) as stub:
        # GET with query params stripped
        status, body = _get(f"{stub.url()}/test/item?filter=all&page=2")
        assert status == 200
        assert body["name"] == "sample"

        # POST with payload
        post_data = {"key": "value123"}
        status, body = _post(f"{stub.url()}/test/submit", post_data)
        assert status == 201
        assert body["accepted"] is True

        # Unknown route returns 404
        status, body = _get(f"{stub.url()}/unknown")
        assert status == 404
        assert body["ok"] is False

        # Verify received recording
        assert len(stub.received) == 3
        assert stub.received[0][0] == "GET"
        assert stub.received[0][1] == "/test/item?filter=all&page=2"
        assert stub.received[1][0] == "POST"
        assert stub.received[1][1] == "/test/submit"
        assert json.loads(stub.received[1][2]) == post_data
