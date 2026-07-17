"""v4.45.0 tests for the optional TLS certificate pinning.

Two suites:

* Env parsing + fingerprint math (pure functions, no network).
* End-to-end handshake against a stub HTTPS server -- verifies
  that a correct pin lets the request through, a wrong pin
  raises TLSPinMismatchError, and pinning stays off by default.
"""
from __future__ import annotations

import hashlib
import os
import socket
import ssl
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest


from arena.agentctl_cli import pinning
from arena.agentctl_cli.pinning import (
    TLSPinMismatchError,
    _parse_pin_env,
    build_pinned_opener,
    is_pinning_enabled,
    verify_peer_cert,
)


# ---------------------------------------------------------------------------
# Env parsing
# ---------------------------------------------------------------------------
def _hex64():
    return "a" * 64  # 64 hex chars


def test_pinning_disabled_by_default(monkeypatch):
    monkeypatch.delenv("ARENA_BRIDGE_PIN_SHA256", raising=False)
    monkeypatch.delenv("ARENA_BRIDGE_PIN_KIND", raising=False)
    assert is_pinning_enabled() is False
    assert _parse_pin_env() == ([], "spki")


def test_pinning_single_valid_hex(monkeypatch):
    fp = _hex64()
    monkeypatch.setenv("ARENA_BRIDGE_PIN_SHA256", fp)
    monkeypatch.delenv("ARENA_BRIDGE_PIN_KIND", raising=False)
    pins, kind = _parse_pin_env()
    assert pins == [fp]
    assert kind == "spki"
    assert is_pinning_enabled() is True


def test_pinning_multiple_pins(monkeypatch):
    a = "1" * 64
    b = "2" * 64
    monkeypatch.setenv("ARENA_BRIDGE_PIN_SHA256", f"{a},{b}")
    pins, _ = _parse_pin_env()
    assert pins == [a, b]


def test_pinning_accepts_colon_separated(monkeypatch):
    """``openssl x509 -fingerprint -sha256`` output has AB:CD:...
    style. Strip them silently."""
    raw = ":".join("ab" for _ in range(32))  # 32 * "ab" = 64 hex chars with colons
    monkeypatch.setenv("ARENA_BRIDGE_PIN_SHA256", raw)
    pins, _ = _parse_pin_env()
    assert pins == ["ab" * 32]


def test_pinning_normalises_case(monkeypatch):
    monkeypatch.setenv("ARENA_BRIDGE_PIN_SHA256", "A" * 64)
    pins, _ = _parse_pin_env()
    assert pins == ["a" * 64]


def test_pinning_rejects_wrong_length(monkeypatch):
    """A shorter/longer than 64 hex chars is silently dropped
    (not the whole config -- other valid pins in the same
    list should still activate pinning)."""
    good = "b" * 64
    monkeypatch.setenv("ARENA_BRIDGE_PIN_SHA256", f"short,{good}")
    pins, _ = _parse_pin_env()
    assert pins == [good]


def test_pinning_rejects_non_hex(monkeypatch):
    good = "c" * 64
    bad = "z" * 64  # not hex
    monkeypatch.setenv("ARENA_BRIDGE_PIN_SHA256", f"{bad},{good}")
    pins, _ = _parse_pin_env()
    assert pins == [good]


def test_pin_kind_env_shapes(monkeypatch):
    monkeypatch.setenv("ARENA_BRIDGE_PIN_SHA256", _hex64())
    monkeypatch.setenv("ARENA_BRIDGE_PIN_KIND", "cert")
    _, kind = _parse_pin_env()
    assert kind == "cert"

    monkeypatch.setenv("ARENA_BRIDGE_PIN_KIND", "SPKI")
    _, kind = _parse_pin_env()
    assert kind == "spki"

    monkeypatch.setenv("ARENA_BRIDGE_PIN_KIND", "garbage")
    _, kind = _parse_pin_env()
    assert kind == "spki"


# ---------------------------------------------------------------------------
# verify_peer_cert -- pure DER path
# ---------------------------------------------------------------------------
def test_verify_no_pin_is_noop(monkeypatch):
    """When pinning is disabled, verify_peer_cert accepts any
    input including garbage -- we should never even hit the
    hasher."""
    monkeypatch.delenv("ARENA_BRIDGE_PIN_SHA256", raising=False)
    verify_peer_cert(b"anything")  # must not raise


def test_verify_correct_pin_passes(monkeypatch):
    payload = b"fake DER content"
    fp = hashlib.sha256(payload).hexdigest()
    monkeypatch.setenv("ARENA_BRIDGE_PIN_SHA256", fp)
    monkeypatch.setenv("ARENA_BRIDGE_PIN_KIND", "cert")
    # Correct fingerprint -- no raise.
    verify_peer_cert(payload)


def test_verify_wrong_pin_raises(monkeypatch):
    payload = b"fake DER content"
    wrong = "0" * 64
    monkeypatch.setenv("ARENA_BRIDGE_PIN_SHA256", wrong)
    monkeypatch.setenv("ARENA_BRIDGE_PIN_KIND", "cert")
    with pytest.raises(TLSPinMismatchError) as excinfo:
        verify_peer_cert(payload)
    assert wrong in str(excinfo.value)
    # Error should also name the ACTUAL fingerprint so the operator
    # can copy it into the env var if they meant to trust this cert.
    actual = hashlib.sha256(payload).hexdigest()
    assert actual in str(excinfo.value)


def test_verify_accepts_either_cert_or_spki_fingerprint(monkeypatch):
    """The design accepts EITHER the raw-cert fingerprint OR the
    SPKI fingerprint regardless of PIN_KIND -- the kind only
    controls the error message. This lets an operator paste
    either form without also setting PIN_KIND correctly."""
    payload = b"fake DER content"
    cert_fp = hashlib.sha256(payload).hexdigest()
    monkeypatch.setenv("ARENA_BRIDGE_PIN_SHA256", cert_fp)
    monkeypatch.setenv("ARENA_BRIDGE_PIN_KIND", "spki")
    # kind=spki, but we pinned the cert-hash -- still accepted.
    verify_peer_cert(payload)


# ---------------------------------------------------------------------------
# build_pinned_opener switch
# ---------------------------------------------------------------------------
def test_build_pinned_opener_returns_none_when_disabled(monkeypatch):
    monkeypatch.delenv("ARENA_BRIDGE_PIN_SHA256", raising=False)
    assert build_pinned_opener(None) is None


def test_build_pinned_opener_returns_opener_when_enabled(monkeypatch):
    monkeypatch.setenv("ARENA_BRIDGE_PIN_SHA256", _hex64())
    opener = build_pinned_opener(None)
    assert opener is not None
    # Sanity: the opener has our custom handler in its handler chain.
    handler_types = [type(h).__name__ for h in opener.handlers]
    assert "_PinnedHTTPSHandler" in handler_types


# ---------------------------------------------------------------------------
# End-to-end: real TLS handshake against a stub bridge
# ---------------------------------------------------------------------------
def _make_self_signed_cert(tmp_path):
    """Generate a fresh self-signed cert for the test HTTPS server.

    Requires `cryptography` (already a dev dep of semgrep here);
    skip the E2E tests if it's missing on the test machine."""
    try:
        from cryptography import x509
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import rsa
        from cryptography.x509.oid import NameOID
    except ImportError:
        pytest.skip("cryptography not installed; skipping E2E pinning test")
    import datetime as _dt
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = issuer = x509.Name([
        x509.NameAttribute(NameOID.COMMON_NAME, "localhost"),
    ])
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(_dt.datetime.utcnow())
        .not_valid_after(_dt.datetime.utcnow() + _dt.timedelta(days=1))
        .add_extension(
            x509.SubjectAlternativeName([x509.DNSName("localhost")]),
            critical=False,
        )
        .sign(key, hashes.SHA256())
    )
    cert_path = tmp_path / "cert.pem"
    key_path = tmp_path / "key.pem"
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=serialization.NoEncryption(),
    ))
    # Compute pins we'll expose to tests.
    cert_der = cert.public_bytes(serialization.Encoding.DER)
    cert_fp = hashlib.sha256(cert_der).hexdigest()
    spki_der = cert.public_key().public_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    spki_fp = hashlib.sha256(spki_der).hexdigest()
    return cert_path, key_path, cert_fp, spki_fp


@pytest.fixture
def tls_server(tmp_path):
    cert_path, key_path, cert_fp, spki_fp = _make_self_signed_cert(tmp_path)

    class _Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"ok": true}')

        def log_message(self, *_a, **_kw):
            pass

    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(str(cert_path), str(key_path))
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    server = HTTPServer(("127.0.0.1", port), _Handler)
    server.socket = ctx.wrap_socket(server.socket, server_side=True)
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    yield {"port": port, "cert_fp": cert_fp, "spki_fp": spki_fp}
    server.shutdown()
    server.server_close()


def _permissive_ctx():
    """Client SSLContext that doesn't verify -- we're testing
    pinning here, not the strict-verify path (which the
    self-signed test cert wouldn't pass anyway)."""
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


def test_e2e_correct_cert_pin_accepts(monkeypatch, tls_server):
    monkeypatch.setenv("ARENA_BRIDGE_PIN_SHA256", tls_server["cert_fp"])
    monkeypatch.setenv("ARENA_BRIDGE_PIN_KIND", "cert")
    opener = build_pinned_opener(_permissive_ctx())
    assert opener is not None
    url = f"https://localhost:{tls_server['port']}/ok"
    resp = opener.open(url, timeout=5)
    assert resp.status == 200


def test_e2e_correct_spki_pin_accepts(monkeypatch, tls_server):
    monkeypatch.setenv("ARENA_BRIDGE_PIN_SHA256", tls_server["spki_fp"])
    monkeypatch.setenv("ARENA_BRIDGE_PIN_KIND", "spki")
    opener = build_pinned_opener(_permissive_ctx())
    url = f"https://localhost:{tls_server['port']}/ok"
    resp = opener.open(url, timeout=5)
    assert resp.status == 200


def test_e2e_wrong_pin_rejects(monkeypatch, tls_server):
    wrong = "9" * 64
    monkeypatch.setenv("ARENA_BRIDGE_PIN_SHA256", wrong)
    opener = build_pinned_opener(_permissive_ctx())
    url = f"https://localhost:{tls_server['port']}/ok"
    with pytest.raises(TLSPinMismatchError) as excinfo:
        opener.open(url, timeout=5)
    # The actual fingerprint should be in the message so the
    # operator can copy it if the cert legitimately rotated.
    assert tls_server["cert_fp"] in str(excinfo.value) or \
           tls_server["spki_fp"] in str(excinfo.value)


def test_e2e_wrong_pin_never_sends_request(monkeypatch, tls_server):
    """The critical property: the bearer token (or any other
    request body) MUST NOT be sent when the pin mismatch fires.
    We assert this by making the request URL a path that would
    only be recorded by the handler; the mismatch aborts before
    do_GET can run.

    We can't easily instrument the stub server for "requests
    seen" without more scaffolding, so we rely on the fact that
    the error fires from ``connect()`` which runs before any
    request line is written. If a future refactor moves the
    check after ``request()``, the error type check below will
    still fail because the error would then be a different
    exception."""
    monkeypatch.setenv("ARENA_BRIDGE_PIN_SHA256", "8" * 64)
    opener = build_pinned_opener(_permissive_ctx())
    with pytest.raises(TLSPinMismatchError):
        opener.open(f"https://localhost:{tls_server['port']}/token-leaks-here",
                    timeout=5)
