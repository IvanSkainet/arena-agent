#!/usr/bin/env python3
"""Arena Bridge real health, auth, and reachability diagnostic CLI.

Performs an end-to-end verification of:
1. Local loopback daemon and /health endpoint;
2. Bearer token authentication against /v1/self;
3. Tunnel provider status (Tailscale Funnel, Cloudflare, ngrok, bore);
4. Real probe against the public tunnel URL to prove external reachability;
5. Clear, actionable summary card with copy-paste URL and token for Arena.ai.
"""
from __future__ import annotations

import argparse
import json
import os
import ssl
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent


def _ssl_context() -> ssl.SSLContext:
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


def _read_token(token_file: Path | str | None = None) -> str:
    candidates = [
        Path(token_file) if token_file else None,
        ROOT / "token.txt",
        Path.home() / "arena-bridge" / "token.txt",
        Path.home() / ".arena" / "token.txt",
    ]
    for c in candidates:
        if c and c.is_file():
            try:
                tok = c.read_text(encoding="utf-8").strip()
                if tok:
                    return tok
            except Exception:
                pass
    return os.environ.get("ARENA_BRIDGE_TOKEN", "")


def probe_bridge(
    port: int = 8765,
    token: str = "",
    host: str = "127.0.0.1",
    timeout: float = 5.0,
) -> dict[str, Any]:
    """Run full diagnostic against the running bridge."""
    report: dict[str, Any] = {
        "ok": False,
        "local_online": False,
        "auth_ok": False,
        "version": None,
        "profile": None,
        "tools_count": 0,
        "tunnels": {},
        "public_url": None,
        "public_reachable": False,
        "errors": [],
    }

    local_base = f"http://{host}:{port}"

    # 1. Probe local /health and /v1/version
    try:
        req = urllib.request.Request(f"{local_base}/v1/version", headers={"User-Agent": "arena-doctor"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            v_data = json.loads(resp.read().decode("utf-8", "ignore"))
            report["local_online"] = True
            report["version"] = v_data.get("version")
    except Exception as e:
        report["errors"].append(f"Local bridge on {local_base} not responding: {e}")
        return report

    # 2. Probe /v1/self with bearer token
    if not token:
        token = _read_token()

    if not token:
        report["errors"].append("No bearer token found (token.txt is missing or empty)")
    else:
        try:
            req = urllib.request.Request(
                f"{local_base}/v1/self",
                headers={"Authorization": f"Bearer {token}", "User-Agent": "arena-doctor"},
            )
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                s_data = json.loads(resp.read().decode("utf-8", "ignore"))
                if s_data.get("ok"):
                    report["auth_ok"] = True
                    report["tools_count"] = s_data.get("tool_count", 0)
        except urllib.error.HTTPError as e:
            if e.code == 401:
                report["errors"].append(f"Authentication failed (401 Unauthorized) with token '{token[:6]}...'")
            else:
                report["errors"].append(f"/v1/self returned HTTP {e.code}")
        except Exception as e:
            report["errors"].append(f"/v1/self probe error: {e}")

    # 3. Probe /v1/access for remote reachability & tunnels
    if report["auth_ok"]:
        try:
            req = urllib.request.Request(
                f"{local_base}/v1/access",
                headers={"Authorization": f"Bearer {token}", "User-Agent": "arena-doctor"},
            )
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                acc = json.loads(resp.read().decode("utf-8", "ignore"))
                tunnel_urls = acc.get("tunnel_urls", [])
                if tunnel_urls:
                    report["public_url"] = tunnel_urls[0]
        except Exception:
            pass

        # 4. Probe /v1/tunnels/status for providers
        try:
            req = urllib.request.Request(
                f"{local_base}/v1/tunnels/status",
                headers={"Authorization": f"Bearer {token}", "User-Agent": "arena-doctor"},
            )
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                t_snap = json.loads(resp.read().decode("utf-8", "ignore"))
                providers = t_snap.get("providers", {})
                if isinstance(providers, list):
                    providers = {p.get("provider", f"tun_{i}"): p for i, p in enumerate(providers)}
                report["tunnels"] = providers
                for p_name, p_data in providers.items():
                    if p_data.get("active") and p_data.get("public_url"):
                        report["public_url"] = p_data.get("public_url")
        except Exception:
            pass

    # 5. Real external probe of the public tunnel URL
    if report["public_url"]:
        p_url = report["public_url"].rstrip("/")
        try:
            probe_req = urllib.request.Request(
                f"{p_url}/v1/version",
                headers={"User-Agent": "arena-doctor-probe"},
            )
            with urllib.request.urlopen(probe_req, context=_ssl_context(), timeout=timeout + 2) as p_resp:
                p_data = json.loads(p_resp.read().decode("utf-8", "ignore"))
                if p_data.get("ok"):
                    report["public_reachable"] = True
        except Exception as e:
            report["errors"].append(f"Public tunnel URL {p_url} failed probe: {e}")

    report["ok"] = report["local_online"] and report["auth_ok"] and (report["public_reachable"] or not report["public_url"])
    return report


def print_summary(report: dict[str, Any], token: str = "") -> None:
    print("\n" + "=" * 62)
    print("  Arena Bridge — Real Health & Reachability Diagnostic")
    print("=" * 62)

    if not report["local_online"]:
        print("  [ERROR] Bridge is DOWN (not listening on local port)")
        print("\n  To start the bridge:")
        print("    Windows: double-click start.bat")
        print("    Linux/macOS: ./start.sh")
        print("=" * 62 + "\n")
        return

    ver_str = f"v{report['version']}" if report["version"] else "unknown"
    print(f"  Bridge Status:      ONLINE ({ver_str})")
    print("  Local Endpoint:     http://127.0.0.1:8765")
    auth_str = f"OK ({report['tools_count']} tools available)" if report["auth_ok"] else "FAIL (invalid or missing token)"
    print(f"  Authentication:     {auth_str}")

    print("\n  Remote Access / Tunnels:")
    tunnels = report.get("tunnels", {})
    if not tunnels:
        print("    (no tunnel providers configured)")
    for name, data in sorted(tunnels.items()):
        status_label = "ACTIVE" if data.get("active") else "INACTIVE"
        url = data.get("public_url") or ""
        print(f"    - {name:<12s}: {status_label:<8s} {url}")

    if report["public_url"]:
        reach_label = "[REACHABLE]" if report["public_reachable"] else "[FAILED PROBE - CHECK SSL/NETWORK]"
        print(f"\n  Public Tunnel:      {report['public_url']} {reach_label}")
    else:
        print("\n  Public Tunnel:      NONE ACTIVE (Loopback only)")

    tok_val = token or _read_token()
    if report["auth_ok"]:
        best_url = report["public_url"] if report["public_reachable"] else "http://127.0.0.1:8765"
        print("\n" + "-" * 62)
        print("  >>> ДАННЫЕ ДЛЯ ПОДКЛЮЧЕНИЯ В ARENA.AI / АГЕНТА:")
        print(f"  URL:   {best_url}")
        print(f"  Token: {tok_val}")
        print("-" * 62)

    if report["errors"]:
        print("\n  Warnings / Errors:")
        for err in report["errors"]:
            print(f"    ! {err}")

    print("=" * 62 + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8765, help="Bridge local port (default: 8765)")
    parser.add_argument("--token", default="", help="Bearer token (default: reads token.txt)")
    parser.add_argument("--json", action="store_true", help="Print JSON report")
    args = parser.parse_args()

    report = probe_bridge(port=args.port, token=args.token)
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print_summary(report, token=args.token)

    return 0 if (report["local_online"] and report["auth_ok"]) else 1


if __name__ == "__main__":
    sys.exit(main())
