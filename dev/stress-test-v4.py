#!/usr/bin/env python3
"""Arena Unified Bridge stress/smoke test v4.

Capability-aware cross-platform smoke suite. It deliberately treats unsupported
features as SKIP when /v1/capabilities says the backend is unavailable. The
default run is non-persistent; use --task-roundtrip and/or --restart for
mutating/disruptive checks.

Usage:
    python dev/stress-test-v4.py --url http://127.0.0.1:8765 --token TOKEN
    python dev/stress-test-v4.py --url https://pc.tail.ts.net --token TOKEN --restart
    python dev/stress-test-v4.py --url http://127.0.0.1:8765 --token TOKEN --task-roundtrip
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any


@dataclass
class Result:
    name: str
    status: str
    detail: str = ""
    duration_ms: int = 0


class BridgeClient:
    def __init__(self, base_url: str, token: str, timeout: float = 30.0):
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.timeout = timeout

    def request(self, method: str, path: str, body: dict | None = None) -> tuple[int, Any, str]:
        data = None
        headers = {"Authorization": f"Bearer {self.token}"}
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(self.base_url + path, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                raw = r.read()
                text = raw.decode("utf-8", errors="replace")
                try:
                    parsed = json.loads(text) if text else None
                except Exception:
                    parsed = text
                return r.status, parsed, text
        except urllib.error.HTTPError as e:
            raw = e.read()
            text = raw.decode("utf-8", errors="replace")
            try:
                parsed = json.loads(text) if text else None
            except Exception:
                parsed = text
            return e.code, parsed, text


def run_check(name: str, fn) -> Result:
    t0 = time.time()
    try:
        status, detail = fn()
        return Result(name, status, detail, int((time.time() - t0) * 1000))
    except Exception as e:
        return Result(name, "FAIL", f"{type(e).__name__}: {e}", int((time.time() - t0) * 1000))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", required=True)
    ap.add_argument("--token", required=True)
    ap.add_argument("--restart", action="store_true", help="also test POST /v1/restart (mutating/disruptive)")
    ap.add_argument("--task-roundtrip", action="store_true", help="submit a tiny echo task (mutating; leaves queue history)")
    ap.add_argument("--timeout", type=float, default=30.0)
    args = ap.parse_args()

    c = BridgeClient(args.url, args.token, args.timeout)
    results: list[Result] = []
    caps: dict[str, Any] = {}

    def json_ok(path: str, key: str = "ok"):
        code, data, _ = c.request("GET", path)
        if code != 200:
            return "FAIL", f"HTTP {code}"
        if not isinstance(data, dict):
            return "FAIL", "non-JSON response"
        if key and not data.get(key):
            return "FAIL", f"{path} ok=false: {data.get('error') or data}"
        return "PASS", ""

    for path in [
        "/health",
        "/v1/version",
        "/v1/status",
        "/v1/sysinfo",
        "/v1/doctor",
        "/v1/metrics",
        "/v1/service/info",
        "/v1/sys/svc",
        "/v1/hardware?include_inventory=0&timeout=90",
        "/v1/skills",
        "/v1/cdp/status",
        "/v1/browser/cdp/session/check",  # ok=false is valid when disconnected; special below
    ]:
        if path.endswith("session/check"):
            def fn(path=path):
                code, data, _ = c.request("GET", path)
                if code != 200:
                    return "FAIL", f"HTTP {code}"
                if not isinstance(data, dict):
                    return "FAIL", "non-JSON response"
                return "PASS", f"connected={data.get('connected')} ok={data.get('ok')}"
            results.append(run_check(path, fn))
        else:
            results.append(run_check(path, lambda path=path: json_ok(path)))

    def cap_check():
        nonlocal caps
        code, data, _ = c.request("GET", "/v1/capabilities")
        if code != 200 or not isinstance(data, dict) or not data.get("ok"):
            return "FAIL", f"HTTP {code} {data}"
        caps = data
        return "PASS", f"platform={data.get('platform', {}).get('system')}"
    results.append(run_check("/v1/capabilities", cap_check))

    # Capability-aware desktop checks.
    desktop = caps.get("desktop", {}) if caps else {}
    if desktop.get("windows", {}).get("available"):
        results.append(run_check("/v1/desktop/windows", lambda: json_ok("/v1/desktop/windows")))
    else:
        results.append(Result("/v1/desktop/windows", "SKIP", desktop.get("windows", {}).get("reason", "not available")))

    if desktop.get("active_window", {}).get("available"):
        results.append(run_check("/v1/desktop/active_window", lambda: json_ok("/v1/desktop/active_window")))
    else:
        results.append(Result("/v1/desktop/active_window", "SKIP", desktop.get("active_window", {}).get("reason", "not available")))

    if desktop.get("screenshot", {}).get("available"):
        def shot():
            code, _data, text = c.request("GET", "/v1/desktop/screenshot?format=jpeg&max_width=640&quality=70")
            return ("PASS", f"HTTP {code}") if code == 200 else ("FAIL", f"HTTP {code} {text[:200]}")
        results.append(run_check("/v1/desktop/screenshot", shot))
    else:
        results.append(Result("/v1/desktop/screenshot", "SKIP", desktop.get("screenshot", {}).get("reason", "not available")))

    # Non-mutating task queue check by default. Submitting tasks is useful but
    # leaves queue history, so require --task-roundtrip for that.
    results.append(run_check("/v1/tasks", lambda: json_ok("/v1/tasks?limit=5")))

    if args.task_roundtrip:
        def task_roundtrip():
            # Use a cross-shell benign command instead of a title-only task.
            # Title-only tasks used to become `# title` and fail on Windows cmd.
            code, data, _ = c.request("POST", "/v1/tasks", {"cmd": "echo stress-test-v4 noop", "title": "stress-test-v4 noop"})
            if code != 200 or not isinstance(data, dict) or not data.get("ok"):
                return "FAIL", f"submit failed HTTP {code}: {data}"
            code, data, _ = c.request("GET", "/v1/tasks?limit=5")
            if code != 200 or not isinstance(data, dict) or not data.get("ok"):
                return "FAIL", f"list failed HTTP {code}: {data}"
            return "PASS", ""
        results.append(run_check("tasks roundtrip", task_roundtrip))

    if args.restart:
        def restart_check():
            pre_uptime = None
            try:
                code, h0, _ = c.request("GET", "/health")
                if code == 200 and isinstance(h0, dict):
                    pre_uptime = float(h0.get("uptime_seconds") or 0)
            except Exception:
                pass
            code, data, _ = c.request("POST", "/v1/restart", {})
            if code != 200 or not isinstance(data, dict) or not data.get("ok"):
                return "FAIL", f"restart request failed HTTP {code}: {data}"
            # The old process may still answer for ~1.5s after the response.
            # Wait until /health returns from a process whose uptime is lower
            # than the pre-restart uptime (or simply very low if pre is absent).
            deadline = time.time() + 90
            last = ""
            while time.time() < deadline:
                try:
                    code, h, _ = c.request("GET", "/health")
                    if code == 200 and isinstance(h, dict) and h.get("ok"):
                        uptime = float(h.get("uptime_seconds") or 0)
                        if pre_uptime is None or uptime < max(5.0, pre_uptime):
                            return "PASS", f"version={h.get('version')} uptime={uptime} pre_uptime={pre_uptime}"
                        last = f"old process still answering uptime={uptime} pre={pre_uptime}"
                except Exception as e:
                    last = str(e)
                time.sleep(2)
            return "FAIL", f"health did not recover after restart: {last}"
        results.append(run_check("POST /v1/restart", restart_check))

    width = max(len(r.name) for r in results)
    counts: dict[str, int] = {}
    for r in results:
        counts[r.status] = counts.get(r.status, 0) + 1
        print(f"{r.status:<4} {r.name:<{width}} {r.duration_ms:>5}ms {r.detail}")
    print("\nSummary:", " ".join(f"{k}={v}" for k, v in sorted(counts.items())))
    return 1 if counts.get("FAIL") else 0


if __name__ == "__main__":
    raise SystemExit(main())
