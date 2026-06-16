"""Extracted module from scripts/cdp_browser.py."""
from __future__ import annotations

from arena.browser.cdp_client.common import *  # noqa: F401,F403

from arena.browser.cdp_client.process import launch_browser
from arena.browser.cdp_client.tabs_http import get_websocket_url

class SyncCDPBrowser:
    """Synchronous CDP browser using raw socket WebSocket.
    Used as a fallback when aiohttp is not available.

    This preserves the original functionality of cdp_browser.py
    while adding incremental request IDs and basic timeouts.
    """

    def __init__(self, port: int = DEFAULT_PORT):
        self.port = port
        self.sock = None
        self._req_id = itertools.count(1)

    def connect(self) -> None:
        ws_url = get_websocket_url(self.port)
        if not ws_url:
            launch_browser(self.port)
            ws_url = get_websocket_url(self.port)
        if not ws_url:
            raise ConnectionError(f"Cannot connect to CDP port {self.port}")
        self.sock = self._perform_handshake(ws_url)
        # Enable core domains (backward compat: always enable on connect)
        self.call("Page.enable")
        self.call("Runtime.enable")

    def close(self) -> None:
        if self.sock:
            self.sock.close()
            self.sock = None

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, *args):
        self.close()

    def _perform_handshake(self, ws_url: str):
        import urllib.parse as up
        import socket as _socket
        import struct as _struct

        parsed = up.urlparse(ws_url)
        host = parsed.hostname
        port = parsed.port or 9222
        path = parsed.path
        if parsed.query:
            path += "?" + parsed.query

        sock = _socket.socket(_socket.AF_INET, _socket.SOCK_STREAM)
        sock.settimeout(10)
        sock.connect((host, port))

        handshake = (
            f"GET {path} HTTP/1.1\r\n"
            f"Host: {host}:{port}\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            "Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==\r\n"
            "Sec-WebSocket-Version: 13\r\n\r\n"
        )
        sock.sendall(handshake.encode())

        resp = b""
        while b"\r\n\r\n" not in resp:
            chunk = sock.recv(1)
            if not chunk:
                break
            resp += chunk
        return sock

    @staticmethod
    def _send_frame(sock, data: str) -> None:
        import struct as _struct
        import os as _os

        payload = data.encode("utf-8")
        length = len(payload)
        mask = _os.urandom(4)
        header = bytearray([0x81])
        if length < 126:
            header.append(length | 0x80)
        elif length <= 65535:
            header.append(126 | 0x80)
            header.extend(_struct.pack("!H", length))
        else:
            header.append(127 | 0x80)
            header.extend(_struct.pack("!Q", length))
        header.extend(mask)

        masked = bytearray(length)
        for i in range(length):
            masked[i] = payload[i] ^ mask[i % 4]
        sock.sendall(header + masked)

    @staticmethod
    def _recv_frame(sock) -> Optional[str]:
        import struct as _struct

        head = sock.recv(2)
        if not head or len(head) < 2:
            return None
        payload_len = head[1] & 0x7F
        if payload_len == 126:
            ext = sock.recv(2)
            payload_len = _struct.unpack("!H", ext)[0]
        elif payload_len == 127:
            ext = sock.recv(8)
            payload_len = _struct.unpack("!Q", ext)[0]
        # Read full payload (handle partial reads)
        data = b""
        while len(data) < payload_len:
            chunk = sock.recv(payload_len - len(data))
            if not chunk:
                break
            data += chunk
        return data.decode("utf-8", errors="ignore")

    def call(self, method: str, params: Optional[Dict] = None) -> Optional[Dict]:
        msg_id = next(self._req_id)
        msg = {"id": msg_id, "method": method}
        if params:
            msg["params"] = params
        self._send_frame(self.sock, json.dumps(msg))

        while True:
            frame = self._recv_frame(self.sock)
            if not frame:
                break
            try:
                data = json.loads(frame)
                if data.get("id") == msg_id:
                    return data
                # Events are silently ignored in sync mode
            except json.JSONDecodeError:
                continue
        return None

    def navigate(self, url: str) -> None:
        self.call("Page.navigate", {"url": url})
        time.sleep(3)

    def screenshot(self, path: str = "screenshot_cdp.png") -> bool:
        res = self.call("Page.captureScreenshot")
        if res and "result" in res and "data" in res["result"]:
            with open(path, "wb") as f:
                f.write(base64.b64decode(res["result"]["data"]))
            return True
        return False

    def dump_dom(self) -> Optional[str]:
        res = self.call("Runtime.evaluate", {"expression": "document.documentElement.outerHTML"})
        if res and "result" in res and "result" in res["result"]:
            return res["result"]["result"].get("value")
        return None

    def eval_js(self, expression: str) -> Optional[str]:
        res = self.call("Runtime.evaluate", {"expression": expression})
        if res and "result" in res and "result" in res["result"]:
            return json.dumps(res["result"]["result"], indent=2, ensure_ascii=False)
        return None
