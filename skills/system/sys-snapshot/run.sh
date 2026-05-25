#!/usr/bin/env bash
# system/sys-snapshot — снимок состояния всей системы (bridge, MCP, services,
# memory, recent reports, last facts) → JSON-файл + краткий markdown.
#
# Usage: agentctl skill run system/sys-snapshot
set -euo pipefail

OUT_DIR="${ARENA_AGENT_HOME:-$HOME/arena-agent}/reports/snapshots"
mkdir -p "$OUT_DIR"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
JSON="$OUT_DIR/snapshot-${STAMP}.json"
MD="$OUT_DIR/snapshot-${STAMP}.md"

# Собираем всё через python для аккуратного JSON
python3 - "$JSON" "$MD" "$STAMP" <<'PY'
import json, os, subprocess, sys, time
json_path, md_path, stamp = sys.argv[1:4]

def run(cmd, t=10):
    try:
        p = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=t)
        return {"exit": p.returncode, "out": p.stdout.strip()[:4000], "err": p.stderr.strip()[:1000]}
    except Exception as e:
        return {"exit": -1, "out": "", "err": str(e)}

def http_get(url, t=5):
    try:
        import urllib.request
        with urllib.request.urlopen(url, timeout=t) as r: return r.read().decode("utf-8", "replace")
    except Exception as e: return f"<err: {e}>"

snap = {
    "stamp": stamp,
    "host": run("hostname")["out"],
    "uptime": run("uptime -p")["out"],
    "kernel": run("uname -r")["out"],
    "bridge_health": http_get("http://127.0.0.1:8765/health"),
    "mcp_health":    http_get("http://127.0.0.1:8767/health"),
    "ports":         run("ss -tlnp 2>/dev/null | grep -E ':876[5-9]'")["out"],
    "services":      run("systemctl --user --no-pager is-active arena-local-bridge.service arena-mcp-stream.service arena-mcp-ws.service arena-task-runner.service 2>&1")["out"],
    "service_mem":   run("systemctl --user show arena-local-bridge.service arena-mcp-stream.service arena-mcp-ws.service -p MemoryCurrent -p MemoryPeak --no-pager")["out"],
    "disk":          run("df -h ~/arena-agent | tail -1")["out"],
    "shots_count":   run("ls ~/arena-agent/reports/shots/ 2>/dev/null | wc -l")["out"],
    "reports_recent": run("ls -t ~/arena-agent/reports/ 2>/dev/null | head -8")["out"],
    "last_facts":     run("tail -10 ~/arena-agent/memory/facts.jsonl 2>/dev/null")["out"],
    "last_backup":    run("ls -t ~/arena-agent/backups/ 2>/dev/null | head -1")["out"],
}

with open(json_path, "w") as f: json.dump(snap, f, ensure_ascii=False, indent=2)

with open(md_path, "w") as f:
    f.write(f"# Sys Snapshot — {stamp}\n\n")
    for k, v in snap.items():
        if k in ("bridge_health", "mcp_health"):
            f.write(f"## {k}\n```json\n{v}\n```\n\n")
        else:
            f.write(f"## {k}\n```\n{v}\n```\n\n")

print(json.dumps({"ok": True, "json": json_path, "md": md_path, "size_bytes": os.path.getsize(json_path)}))
PY
