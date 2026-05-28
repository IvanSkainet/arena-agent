import sys, os, subprocess, json, threading, time
from http.server import BaseHTTPRequestHandler, HTTPServer

LOG_FILE = os.path.expanduser("~/arena-bridge/audit.jsonl")
PORT = 8766

class LogStreamHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/logs":
            self.send_response(200)
            self.send_header('Content-Type', 'text/event-stream')
            self.send_header('Cache-Control', 'no-cache')
            self.send_header('Connection', 'keep-alive')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            
            try:
                with open(LOG_FILE, 'r') as f:
                    f.seek(0, 2) # Move to end of file
                    while True:
                        line = f.readline()
                        if not line:
                            time.sleep(0.5)
                            continue
                        self.wfile.write(f"data: {line.strip()}\n\n".encode())
                        self.wfile.flush()
            except BrokenPipeError:
                pass # Client disconnected
            except Exception as e:
                print(f"Error streaming logs: {e}")
        else:
            self.send_response(404)
            self.end_headers()

def run_server():
    server = HTTPServer(('127.0.0.1', PORT), LogStreamHandler)
    print(f"Log streaming server running on http://127.0.0.1:{PORT}")
    server.serve_forever()

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "start":
        # Run as a background process
        pid = os.fork()
        if pid == 0:
            os.setsid()
            run_server()
        else:
            print(f"Started log streaming server (PID {pid})")
    elif len(sys.argv) > 1 and sys.argv[1] == "stop":
        os.system(f"pkill -f 'python3.*live_logs_manager.py'")
        print("Stopped log streaming server")
