"""Standalone pure-stdlib MCP WebSocket server components."""
from __future__ import annotations

import base64
import hashlib
import json
import socket
import struct
import sys
import threading
import time
from pathlib import Path

from arena.mcp.standalone_rpc import handle_rpc
from arena.mcp.tool_registry import MCP_TOOLS as TOOLS
from arena.mcp.standalone_common import VERSION

GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"

def _accept_key(key: str) -> str:
    # v4.43.0: SHA-1 here is spec-mandated by RFC 6455 §4.2.2 --
    # the WebSocket handshake proof is literally
    # ``base64(SHA1(client-key || GUID))``. We are not using
    # SHA-1 for a security decision (integrity, authentication,
    # signature); this is a protocol identifier. Passing
    # ``usedforsecurity=False`` tells hashlib exactly that, and
    # also silences bandit B324 on FIPS builds where SHA-1 is
    # blocked from security-use but still allowed for identifier
    # purposes.
    return base64.b64encode(
        hashlib.sha1((key + GUID).encode(),  # nosemgrep: insecure-hash-algorithm-sha1 -- RFC 6455 §4.2.2 protocol identifier, not a security decision; usedforsecurity=False makes hashlib treat it that way too
                     usedforsecurity=False).digest()
    ).decode()

def _read_exact(sock: socket.socket, n: int) -> bytes:
    buf = b""
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk: raise ConnectionError("peer closed")
        buf += chunk
    return buf

def _recv_frame(sock: socket.socket) -> tuple[int, bytes]:
    """Возвращает (opcode, payload). 0x1=text, 0x2=binary, 0x8=close, 0x9=ping."""
    hdr = _read_exact(sock, 2)
    b1, b2 = hdr[0], hdr[1]
    opcode = b1 & 0x0F
    masked = bool(b2 & 0x80)
    plen = b2 & 0x7F
    if plen == 126: plen = struct.unpack(">H", _read_exact(sock, 2))[0]
    elif plen == 127: plen = struct.unpack(">Q", _read_exact(sock, 8))[0]
    mask = _read_exact(sock, 4) if masked else b""
    data = _read_exact(sock, plen) if plen else b""
    if masked:
        data = bytes(b ^ mask[i % 4] for i, b in enumerate(data))
    return opcode, data

def _send_frame(sock: socket.socket, opcode: int, payload: bytes) -> None:
    head = bytes([0x80 | opcode])
    n = len(payload)
    if n < 126:   head += bytes([n])
    elif n < 65536: head += bytes([126]) + struct.pack(">H", n)
    else: head += bytes([127]) + struct.pack(">Q", n)
    sock.sendall(head + payload)

def _send_text(sock, s: str): _send_frame(sock, 0x1, s.encode("utf-8"))

def _http_handshake(sock: socket.socket) -> bool:
    """Парсим HTTP upgrade request. Возвращаем True если успешно."""
    data = b""
    while b"\r\n\r\n" not in data:
        chunk = sock.recv(4096)
        if not chunk: return False
        data += chunk
        if len(data) > 16384: return False
    headers = {}
    for line in data.split(b"\r\n")[1:]:
        if not line: break
        if b":" in line:
            k, v = line.split(b":", 1); headers[k.strip().lower()] = v.strip()
    key = headers.get(b"sec-websocket-key", b"").decode()
    if not key: return False
    accept = _accept_key(key)
    resp = ("HTTP/1.1 101 Switching Protocols\r\n"
            "Upgrade: websocket\r\nConnection: Upgrade\r\n"
            f"Sec-WebSocket-Accept: {accept}\r\n\r\n")
    sock.sendall(resp.encode())
    return True
