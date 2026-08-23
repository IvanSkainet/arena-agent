"""#135: refusal paths must answer, not reset the connection.

`do_POST` checked auth and returned before ever reading the request body.
The client had already sent (or was still sending) its JSON, so the socket
was closed with unread data in the receive buffer -- and the Windows TCP
stack answers that with RST instead of FIN. The caller then sees

    ConnectionAbortedError: [WinError 10053]

instead of the 503 the server had already written.

Measured on a real Windows host against the unfixed gateway, 8 scenarios
(body 27 B and 100 kB, with and without a 50 ms pause before the body, with
and without a half-close): 4 of 8 failed. Every failure had the pause; every
scenario without it passed at both body sizes. So the trigger is the client
still writing when the server closes -- NOT the body exceeding one segment,
which is what the issue proposed testing. After the fix: 0 of 8.

That distinction is why these tests pace the body instead of just making it
large. A single big `sendall` is buffered by the kernel and completes before
the handler refuses, which is exactly the case that already passed.

This is not merely test hygiene: a caller who is refused cannot distinguish
"you are not authorized" from "the service is down" if the connection just
breaks, which defeats the diagnosability half of fail-closed.

Sabotage results, each reverted after: removing the drain fails 4 tests;
keeping the byte cap but dropping the time bound fails 1; inflating the time
cap fails 1. Two further sabotages -- unbounded byte cap, and stripping the
idempotence guards so the drain eats the success path's body -- do NOT fail,
and deliberately so: `do_POST` reads the body before any call to `_json`, so
by the time a drain could run on the success path the body is already
consumed. That was verified by execution (an authorized non-whitelisted
command still answers 403 "not in whitelist", not 400 "missing command"), so
those states are unreachable rather than merely uncovered. If the read is
ever moved after the response, the idempotence guards become load-bearing.
"""

from __future__ import annotations

import importlib.util
import json
import os
import socket
import threading
import time
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

_GW = Path(__file__).resolve().parents[1] / "bin" / "web_gateway.py"


def _load_gateway(token: str | None):
    old = os.environ.get("ARENA_BRIDGE_TOKEN")
    if token is None:
        os.environ.pop("ARENA_BRIDGE_TOKEN", None)
    else:
        os.environ["ARENA_BRIDGE_TOKEN"] = token
    try:
        spec = importlib.util.spec_from_file_location("web_gateway_135", _GW)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        if token is None:
            mod.TOKEN = ""
        return mod
    finally:
        if old is None:
            os.environ.pop("ARENA_BRIDGE_TOKEN", None)
        else:
            os.environ["ARENA_BRIDGE_TOKEN"] = old


@pytest.fixture
def gateway():
    """Serve one gateway per test on an ephemeral port."""
    servers = []

    def _start(token: str | None):
        mod = _load_gateway(token)
        srv = ThreadingHTTPServer(("127.0.0.1", 0), mod.H)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        servers.append(srv)
        return srv.server_address[1]

    yield _start
    for srv in servers:
        srv.shutdown()
        srv.server_close()


def _post_slow_body(port: int, path: str, payload: dict, headers: str = "") -> str:
    """POST with the body sent AFTER a pause, and read the status line.

    The pause is the whole point: it guarantees the handler reaches its
    refusal branch while the client still has bytes outstanding. Returns the
    status line, or raises OSError the way a real client would.
    """
    body = json.dumps(payload).encode()
    sock = socket.create_connection(("127.0.0.1", port), timeout=10)
    try:
        sock.sendall(
            f"POST {path} HTTP/1.1\r\nHost: localhost\r\n"
            f"Content-Type: application/json\r\nContent-Length: {len(body)}\r\n"
            f"{headers}Connection: close\r\n\r\n".encode()
        )
        time.sleep(0.05)          # server refuses here, body still unsent
        sock.sendall(body)
        sock.shutdown(socket.SHUT_WR)
        chunks = []
        while True:
            got = sock.recv(65536)
            if not got:
                break
            chunks.append(got)
        raw = b"".join(chunks)
        assert raw, "server closed without sending any response"
        return raw.split(b"\r\n", 1)[0].decode(errors="replace")
    finally:
        sock.close()


def test_no_token_configured_answers_503_instead_of_resetting(gateway) -> None:
    port = gateway(None)
    status = _post_slow_body(port, "/run", {"command": "agentctl sys status"})
    assert "503" in status, status


def test_missing_token_answers_401_instead_of_resetting(gateway) -> None:
    """Same race, one branch later -- it just wins the race less often."""
    port = gateway("s3cret")
    status = _post_slow_body(port, "/run", {"command": "agentctl sys status"})
    assert "401" in status, status


def test_wrong_token_answers_401_instead_of_resetting(gateway) -> None:
    port = gateway("s3cret")
    status = _post_slow_body(
        port, "/run", {"command": "agentctl sys status"},
        headers="X-Arena-Token: wrong\r\n",
    )
    assert "401" in status, status


def test_refusal_survives_a_multi_segment_body(gateway) -> None:
    """The issue's own criterion: a body far larger than one TCP segment."""
    port = gateway(None)
    status = _post_slow_body(port, "/run", {"command": "x", "pad": "p" * 200_000})
    assert "503" in status, status


def test_unknown_path_still_answers_404(gateway) -> None:
    """404 is reached after the body is read; it must not regress to a reset."""
    port = gateway("s3cret")
    status = _post_slow_body(
        port, "/nope", {"any": "thing"}, headers="X-Arena-Token: s3cret\r\n",
    )
    assert "404" in status, status


def test_authorized_request_still_reads_its_body(gateway) -> None:
    """Draining must not eat the body the success path depends on.

    A drain that ran unconditionally would leave `data` empty and turn every
    authorized /run into "missing command" -- the fix silently breaking the
    feature it protects. `agentctl` is not on the whitelist here only if the
    body was lost, so a 400 "missing command" is the failure signature.
    """
    port = gateway("s3cret")
    status = _post_slow_body(
        port, "/run", {"command": "definitely-not-whitelisted evil"},
        headers="X-Arena-Token: s3cret\r\n",
    )
    # 403 proves the command text arrived and was evaluated by the whitelist.
    assert "403" in status, f"body was lost on the success path: {status}"


def _probe_no_half_close(port: int, declared: int, send: bytes, timeout: float = 6.0) -> str:
    """POST without half-closing, the way a real keep-alive client behaves.

    The half-close in the other helper makes `read()` return EOF immediately,
    which hides a drain that would otherwise block. A first version of this
    fix passed every test here and still hung against this pattern, so the
    two shapes are both kept.
    """
    sock = socket.create_connection(("127.0.0.1", port), timeout=timeout)
    try:
        sock.sendall(
            f"POST /run HTTP/1.1\r\nHost: localhost\r\n"
            f"Content-Type: application/json\r\nContent-Length: {declared}\r\n"
            f"Connection: close\r\n\r\n".encode()
        )
        time.sleep(0.05)
        if send:
            sock.sendall(send)
        try:
            data = b""
            while b"\r\n" not in data:      # a status line may be split across reads
                got = sock.recv(65536)
                if not got:
                    return "EOF" if not data else data.decode(errors="replace")
                data += got
        except socket.timeout:
            return "HANG"
        except OSError:
            return "RESET"
        return data.split(b"\r\n", 1)[0].decode(errors="replace")
    finally:
        sock.close()


def test_a_promised_body_that_never_arrives_does_not_stall_the_handler(gateway) -> None:
    """Declared 1 GB, sent nothing, no half-close.

    The byte cap alone does not help here -- there are no bytes to count, so
    the handler simply blocks in read(). Verified: with only the byte cap this
    hung indefinitely. Draining must be bounded in time as well as in size.
    """
    mod = _load_gateway(None)
    assert mod.H.MAX_DRAIN_SECONDS <= 5, "a refusal must never cost seconds of wall clock"

    port = gateway(None)
    started = time.monotonic()
    status = _probe_no_half_close(port, 1_000_000_000, b"")
    elapsed = time.monotonic() - started
    assert status != "HANG", f"handler stalled for {elapsed:.1f}s on an unsent body"
    assert elapsed < 5, f"refusal took {elapsed:.1f}s"


def test_normal_client_without_half_close_still_gets_its_refusal(gateway) -> None:
    port = gateway(None)
    status = _probe_no_half_close(port, 50, b"y" * 50)
    assert "503" in status, status


def test_drain_is_bounded_so_a_huge_declared_body_cannot_stall_it(gateway) -> None:
    """A liar announcing a giant Content-Length must not pin the handler.

    Politeness toward clients is not an obligation to read 10 GB before
    refusing them.
    """
    mod = _load_gateway(None)
    assert mod.H.MAX_DRAIN_BYTES <= 1 << 20

    port = gateway(None)
    body = b'{"command":"x"}'
    sock = socket.create_connection(("127.0.0.1", port), timeout=10)
    try:
        sock.sendall(
            b"POST /run HTTP/1.1\r\nHost: localhost\r\n"
            b"Content-Type: application/json\r\n"
            b"Content-Length: 10737418240\r\n"      # 10 GB, never sent
            b"Connection: close\r\n\r\n"
        )
        time.sleep(0.05)
        sock.sendall(body)
        sock.shutdown(socket.SHUT_WR)
        started = time.monotonic()
        raw = b""
        while True:
            got = sock.recv(65536)
            if not got:
                break
            raw += got
        assert time.monotonic() - started < 8, "drain did not give up on a bogus length"
        # Either a clean 503 or a reset is acceptable here; hanging is not.
        if raw:
            assert b"503" in raw.split(b"\r\n", 1)[0]
    except OSError:
        pass  # reset on an absurd declared length is a fine outcome
    finally:
        sock.close()


def test_a_body_sent_with_the_headers_is_refused_immediately(gateway) -> None:
    """The common case: one write carrying headers and body together.

    A first version drained `self.connection` directly. BaseHTTPRequestHandler
    parses headers through a buffered `rfile`, so a body in the same packet is
    already in that buffer and invisible to `sock.recv()` -- every ordinary
    refusal then blocked for the full drain timeout. Measured 2.00 s before,
    0.00 s after. Draining reads through `rfile` for exactly this reason.
    """
    port = gateway(None)
    body = json.dumps({"command": "agentctl sys status"}).encode()
    sock = socket.create_connection(("127.0.0.1", port), timeout=15)
    try:
        started = time.monotonic()
        sock.sendall(
            f"POST /run HTTP/1.1\r\nHost: localhost\r\n"
            f"Content-Type: application/json\r\nContent-Length: {len(body)}\r\n"
            f"Connection: close\r\n\r\n".encode() + body      # single write
        )
        raw = b""
        while b"\r\n" not in raw:
            got = sock.recv(65536)
            if not got:
                break
            raw += got
        elapsed = time.monotonic() - started
        assert b"503" in raw.split(b"\r\n", 1)[0], raw[:120]
        assert elapsed < 1.0, f"buffered body cost {elapsed:.2f}s -- drain bypassed rfile"
    finally:
        sock.close()


def test_chunked_body_refusal_is_also_drained(gateway) -> None:
    """`Transfer-Encoding: chunked` carries no Content-Length.

    Reading only Content-Length made `_declared_length()` return 0, the drain
    was skipped, and the refusal reset the connection exactly as before the
    fix. Confirmed on a real Windows host: WinError 10053 for a chunked
    refusal while every Content-Length case already passed.

    Honest limitation: on Linux this assertion passes even with the chunked
    handling removed, because Linux does not send RST for unread data -- the
    same reason the original bug was Windows-only. What this test does hold
    everywhere is the timing assertion below (stopping at the terminator
    rather than burning the full drain budget). The reset itself is only
    observable on Windows, where CI runs it.
    """
    port = gateway(None)
    sock = socket.create_connection(("127.0.0.1", port), timeout=15)
    try:
        sock.sendall(
            b"POST /run HTTP/1.1\r\nHost: localhost\r\n"
            b"Content-Type: application/json\r\n"
            b"Transfer-Encoding: chunked\r\nConnection: close\r\n\r\n"
        )
        time.sleep(0.05)
        started = time.monotonic()
        sock.sendall(b'1b\r\n{"command":"agentctl status"}\r\n0\r\n\r\n')
        raw = b""
        while b"\r\n" not in raw:
            got = sock.recv(65536)
            if not got:
                break
            raw += got
        elapsed = time.monotonic() - started
        assert raw, "chunked refusal reset the connection instead of answering"
        assert b"503" in raw.split(b"\r\n", 1)[0], raw[:120]
        # Stopping at the terminator, not just running out the clock.
        assert elapsed < 1.0, f"chunked drain waited {elapsed:.2f}s for the timeout"
    finally:
        sock.close()
