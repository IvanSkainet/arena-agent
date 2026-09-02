#!/usr/bin/env python3
"""Launcher and helper for Serena MCP server integration.

Enables seamless connection between Skainet Bridge, Claude Code / Cursor,
and Arena Agent Mode for long-term project memory and codebase understanding.

Usage:
    python scripts/start_serena_mcp.py --port 8100 --context claude-code
    python scripts/start_serena_mcp.py --status
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def check_status(port: int = 8100) -> dict[str, bool | str | int]:
    url = f"http://127.0.0.1:{port}/health"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "serena-probe"})
        with urllib.request.urlopen(req, timeout=2.0) as resp:  # nosec B310 -- fixed local Serena MCP endpoint
            data = resp.read()
            return {"ok": True, "status": "running", "port": port, "response": data[:100].decode("utf-8", errors="replace")}
    except Exception as e:
        return {"ok": False, "status": "offline", "port": port, "error": str(e)}


def start_server(port: int = 8100, context: str = "claude-code", project_dir: Path | None = None, transport: str = "streamable-http") -> int:
    target_project = project_dir or ROOT
    serena_bin = shutil.which("serena")
    if not serena_bin:
        print("INFO: 'serena' executable not found on PATH.")
        print(f"To run Serena MCP on host with {context}:")
        print(f"  serena start-mcp-server --context {context} --project \"{target_project}\" --transport {transport} --port {port}")
        return 0

    cmd = [
        serena_bin, "start-mcp-server",
        "--context", context,
        "--project", str(target_project),
        "--transport", transport,
        "--port", str(port),
    ]
    print(f"Starting Serena MCP: {' '.join(cmd)}")
    proc = subprocess.Popen(cmd, cwd=str(target_project))
    print(f"Serena MCP server spawned (PID {proc.pid}) on port {port}.")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Serena MCP helper")
    ap.add_argument("--port", type=int, default=8100, help="MCP server port (default: 8100)")
    ap.add_argument("--context", type=str, default="claude-code", help="Context model (default: claude-code)")
    ap.add_argument("--project", type=Path, default=None, help="Target project directory")
    ap.add_argument("--transport", type=str, default="streamable-http", help="Transport mode")
    ap.add_argument("--status", action="store_true", help="Check Serena server status")
    args = ap.parse_args()

    if args.status:
        st = check_status(args.port)
        print(json.dumps(st, indent=2))
        return 0 if st["ok"] else 1

    return start_server(port=args.port, context=args.context, project_dir=args.project, transport=args.transport)


if __name__ == "__main__":
    sys.exit(main())
