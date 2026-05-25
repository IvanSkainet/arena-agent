import sys
import os
import socket
import struct
import base64
import json
import urllib.request
import subprocess
import time
import platform
import shutil

# Zero-dependency Chrome DevTools Protocol (CDP) controller in pure Python

PORT = 9222
BANNER = "DevTools listening on "

def find_browser_exe():
    chrome_candidates = [
        "chromium", "chrome", "google-chrome", "google-chrome-stable",
        "librewolf", "brave", "brave-browser",
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        os.path.join(os.path.expanduser("~"), "AppData", "Local", "Google", "Chrome", "Application", "chrome.exe"),
        r"C:\Program Files\LibreWolf\librewolf.exe",
        r"C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe",
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        "msedge.exe"
    ]
    for c in chrome_candidates:
        p = shutil.which(c)
        if p: return p
        if os.path.exists(c): return c
    return "chrome.exe" if platform.system() == "Windows" else "chromium"

def launch_browser():
    exe = find_browser_exe()
    print(f"[CDP] Launching browser: {exe}...")
    ud = os.path.join(tempfile.gettempdir(), f"cdp-browser-{os.getpid()}")
    # Launch in headless remote debugging mode
    cmd = [
        exe,
        f"--remote-debugging-port={PORT}",
        "--headless=new",
        "--no-sandbox",
        "--disable-gpu",
        f"--user-data-dir={ud}"
    ]
    # Start process detached
    subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(2) # Give it 2 seconds to start up

def get_websocket_url():
    url = f"http://127.0.0.1:{PORT}/json/list"
    try:
        with urllib.request.urlopen(url, timeout=5) as r:
            tabs = json.loads(r.read().decode())
            for tab in tabs:
                if tab.get("type") == "page" and "webSocketDebuggerUrl" in tab:
                    return tab["webSocketDebuggerUrl"]
    except Exception:
        pass
    return None

def perform_handshake(ws_url):
    parsed = urllib.parse.urlparse(ws_url)
    host = parsed.hostname
    port = parsed.port or 9222
    path = parsed.path
    if parsed.query: path += "?" + parsed.query
    
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.connect((host, port))
    
    # Send WebSocket handshake
    handshake = (
        f"GET {path} HTTP/1.1\r\n"
        f"Host: {host}:{port}\r\n"
        "Upgrade: websocket\r\n"
        "Connection: Upgrade\r\n"
        "Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==\r\n"
        "Sec-WebSocket-Version: 13\r\n\r\n"
    )
    sock.sendall(handshake.encode())
    
    # Read response headers
    resp = b""
    while b"\r\n\r\n" not in resp:
        chunk = sock.recv(1)
        if not chunk: break
        resp += chunk
    return sock

def send_frame(sock, data):
    payload = data.encode('utf-8')
    length = len(payload)
    mask = os.urandom(4)
    header = bytearray([0x81])
    if length < 126:
        header.append(length | 0x80)
    elif length <= 65535:
        header.append(126 | 0x80)
        header.extend(struct.pack("!H", length))
    else:
        header.append(127 | 0x80)
        header.extend(struct.pack("!Q", length))
    header.extend(mask)
    
    masked_payload = bytearray(length)
    for i in range(length):
        masked_payload[i] = payload[i] ^ mask[i % 4]
    sock.sendall(header + masked_payload)

def recv_frame(sock):
    head = sock.recv(2)
    if not head or len(head) < 2: return None
    b1, b2 = head[0], head[1]
    opcode = b1 & 0x0f
    payload_len = b2 & 0x7f
    if payload_len == 126:
        ext = sock.recv(2)
        payload_len = struct.unpack("!H", ext)[0]
    elif payload_len == 127:
        ext = sock.recv(8)
        payload_len = struct.unpack("!Q", ext)[0]
    payload = sock.recv(payload_len)
    return payload.decode('utf-8', errors='ignore')

def call_cdp(sock, method, params=None):
    req_id = 1
    req = {"id": req_id, "method": method}
    if params: req["params"] = params
    send_frame(sock, json.dumps(req))
    
    # Wait for the exact response matching ID
    while True:
        resp_str = recv_frame(sock)
        if not resp_str: break
        try:
            resp = json.loads(resp_str)
            if resp.get("id") == req_id:
                return resp
        except: pass
    return None

import urllib.parse
import tempfile

def main():
    if len(sys.argv) < 2:
        print("Usage: python3 cdp_browser.py <command> [args...]")
        print("Commands:")
        print("  navigate <url>      -> Open browser and navigate to URL")
        print("  shot <png_path>     -> Capture screenshot of active page")
        print("  dump                -> Dump active page outerHTML")
        print("  eval <js>           -> Evaluate JavaScript in page context")
        sys.exit(1)
        
    cmd = sys.argv[1].lower()
    
    # 1. Ensure browser is running and get WS url
    ws_url = get_websocket_url()
    if not ws_url:
        launch_browser()
        ws_url = get_websocket_url()
        if not ws_url:
            print("[ERROR] Could not connect to browser CDP port 9222.", file=sys.stderr)
            sys.exit(1)
            
    # 2. Perform Handshake
    sock = perform_handshake(ws_url)
    
    # Enable Page and Runtime domains
    call_cdp(sock, "Page.enable")
    call_cdp(sock, "Runtime.enable")
    
    if cmd == "navigate":
        if len(sys.argv) < 3:
            print("Provide a URL")
            sys.exit(1)
        url = sys.argv[2]
        print(f"[CDP] Navigating to {url}...")
        call_cdp(sock, "Page.navigate", {"url": url})
        time.sleep(3) # Wait for page load
        print("[OK] Navigation completed successfully.")
        
    elif cmd == "shot":
        path = sys.argv[2] if len(sys.argv) > 2 else "screenshot_cdp.png"
        print(f"[CDP] Capturing screenshot to {path}...")
        res = call_cdp(sock, "Page.captureScreenshot")
        if res and "result" in res and "data" in res["result"]:
            img_b64 = res["result"]["data"]
            open(path, "wb").write(base64.b64decode(img_b64))
            print(f"[OK] Screenshot written to {path} ({os.path.getsize(path)} bytes)")
        else:
            print("[ERROR] Failed to capture screenshot.")
            
    elif cmd == "dump":
        print("[CDP] Dumping DOM (outerHTML)...")
        res = call_cdp(sock, "Runtime.evaluate", {"expression": "document.documentElement.outerHTML"})
        if res and "result" in res and "result" in res["result"] and "value" in res["result"]["result"]:
            print(res["result"]["result"]["value"])
        else:
            print("[ERROR] Failed to dump DOM.")
            
    elif cmd == "eval":
        if len(sys.argv) < 3:
            print("Provide JS expression")
            sys.exit(1)
        expr = " ".join(sys.argv[2:])
        print(f"[CDP] Evaluating: {expr}")
        res = call_cdp(sock, "Runtime.evaluate", {"expression": expr})
        if res and "result" in res and "result" in res["result"]:
            print(json.dumps(res["result"]["result"], indent=2, ensure_ascii=False))
        else:
            print("[ERROR] Failed to evaluate.")
            
    sock.close()

if __name__ == "__main__":
    main()
