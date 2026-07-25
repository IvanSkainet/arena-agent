"""Unit tests for arena.mcp.ws_frames (v4.79.0 coverage lift).

The module implements the WebSocket framing helpers used by the
standalone pure-stdlib MCP server. Until v4.79.0 it had 0% line
coverage (62 statements, 28 branches, never imported by any test).
These tests exercise the pure functions that don't require a real
socket so we can lift coverage without bringing up a listener.
"""
from __future__ import annotations

import socket
import struct

import pytest

from arena.mcp import ws_frames


# --------------------------------------------------------------------
# _accept_key: RFC 6455 §4.2.2 handshake proof
# --------------------------------------------------------------------
def test_accept_key_matches_rfc_6455_vector():
    # The canonical RFC 6455 example: client key
    # "dGhlIHNhbXBsZSBub25jZQ==" must produce the well-known
    # accept value "s3pPLMBiTxaQ9kYGzzhZRbK+xOo=".
    got = ws_frames._accept_key("dGhlIHNhbXBsZSBub25jZQ==")
    assert got == "s3pPLMBiTxaQ9kYGzzhZRbK+xOo="


def test_accept_key_is_deterministic():
    # Same input always yields the same accept value.
    k = "dGhlIHNhbXBsZSBub25jZQ=="
    assert ws_frames._accept_key(k) == ws_frames._accept_key(k)


def test_accept_key_handles_arbitrary_input():
    # Should not raise for any string.
    for k in ("", "abc", "x" * 1024, "non-base64-content", "0" * 24):
        out = ws_frames._accept_key(k)
        assert isinstance(out, str)
        assert len(out) > 0


# --------------------------------------------------------------------
# _read_exact: read exactly N bytes from a socket
# --------------------------------------------------------------------
def _make_socket_pair():
    """Build a connected (a, b) socket pair backed by an in-memory pipe."""
    a, b = socket.socketpair()
    return a, b


def test_read_exact_reads_full_buffer():
    a, b = _make_socket_pair()
    try:
        b.sendall(b"hello world")
        # close the writer so the read sees EOF after the buffer
        b.shutdown(socket.SHUT_WR)
        got = ws_frames._read_exact(a, 5)
        assert got == b"hello"
    finally:
        a.close()
        b.close()


def test_read_exact_raises_on_eof_before_n_bytes():
    a, b = _make_socket_pair()
    try:
        b.sendall(b"hi")
        b.close()
        with pytest.raises(ConnectionError):
            ws_frames._read_exact(a, 10)
    finally:
        a.close()
        b.close()


# --------------------------------------------------------------------
# _send_frame / _send_text: WebSocket framing encoder
# --------------------------------------------------------------------
def test_send_frame_small_payload_unmasked():
    a, b = _make_socket_pair()
    try:
        ws_frames._send_frame(b, 0x1, b"hi")
        # First byte: FIN=1, opcode=0x1 (text). Second byte: MASK=0, len=2.
        first_two = a.recv(2)
        assert first_two[0] == 0x81
        assert first_two[1] == 0x02
        payload = a.recv(2)
        assert payload == b"hi"
    finally:
        a.close()
        b.close()


def test_send_frame_medium_payload_uses_16bit_length():
    a, b = _make_socket_pair()
    try:
        payload = b"x" * 200
        ws_frames._send_frame(b, 0x2, payload)
        hdr = a.recv(2)
        assert hdr[0] == 0x82  # FIN + binary
        assert hdr[1] == 126  # 16-bit length follows
        ln = struct.unpack(">H", a.recv(2))[0]
        assert ln == 200
        body = b""
        while len(body) < 200:
            body += a.recv(200 - len(body))
        assert body == payload
    finally:
        a.close()
        b.close()


def test_send_text_encodes_utf8():
    a, b = _make_socket_pair()
    try:
        ws_frames._send_text(b, "café")
        # 5 UTF-8 bytes: c, a, f, é(2 bytes)
        a.recv(2)  # discard the opcode+length header
        body = a.recv(5)
        assert body == "café".encode("utf-8")
    finally:
        a.close()
        b.close()


# --------------------------------------------------------------------
# _recv_frame: WebSocket frame decoder
# --------------------------------------------------------------------
def test_recv_frame_round_trip_small():
    a, b = _make_socket_pair()
    try:
        ws_frames._send_frame(b, 0x1, b"ping")
        a.settimeout(1.0)
        opcode, payload = ws_frames._recv_frame(a)
        assert opcode == 0x1
        assert payload == b"ping"
    finally:
        a.close()
        b.close()


def test_recv_frame_handles_close_opcode():
    a, b = _make_socket_pair()
    try:
        ws_frames._send_frame(b, 0x8, b"")
        a.settimeout(1.0)
        opcode, payload = ws_frames._recv_frame(a)
        assert opcode == 0x8
        assert payload == b""
    finally:
        a.close()
        b.close()
