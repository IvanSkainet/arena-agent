#!/usr/bin/env python3
"""
recon_ip.py — Cross-platform public IP / location lookup.

Replaces the old recon_ip.sh. Uses Python's urllib (no curl required).

Calls (parallel, with 5s timeout each):
    https://api.ipify.org           -> plain text IP
    https://ifconfig.me/ip          -> plain text IP
    https://ifconfig.co/json        -> {ip, country, city, asn, ...}
    https://www.cloudflare.com/cdn-cgi/trace  -> key=value lines

Usage:
    recon_ip.py             # human-readable
    recon_ip.py --json      # JSON
    recon_ip.py --quiet     # only the most likely IP, one line
"""
from __future__ import annotations
import sys
import json
import argparse
import urllib.request
import urllib.error
import socket
from concurrent.futures import ThreadPoolExecutor, as_completed


PROBES = [
    ("ipify", "https://api.ipify.org", "text"),
    ("ifconfig.me", "https://ifconfig.me/ip", "text"),
    ("ifconfig.co", "https://ifconfig.co/json", "json"),
    ("cloudflare", "https://www.cloudflare.com/cdn-cgi/trace", "trace"),
    ("ipinfo.io", "https://ipinfo.io/json", "json"),
]


def _fetch(url: str, timeout: float = 5.0) -> tuple[int, str]:
    """Return (http_status, body_or_error)."""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "arena-recon-ip/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, f"HTTP {e.code}"
    except urllib.error.URLError as e:
        return 0, f"URLError: {e.reason}"
    except socket.timeout:
        return 0, "timeout"
    except Exception as e:
        return 0, f"{type(e).__name__}: {e}"


def _parse(kind: str, body: str) -> dict:
    body = body.strip()
    if kind == "text":
        return {"ip": body}
    if kind == "json":
        try:
            return json.loads(body)
        except Exception:
            return {"raw": body}
    if kind == "trace":
        out: dict[str, str] = {}
        for line in body.splitlines():
            if "=" in line:
                k, v = line.split("=", 1)
                out[k.strip()] = v.strip()
        return out
    return {"raw": body}


def collect(timeout: float = 5.0) -> dict:
    results: dict = {}
    with ThreadPoolExecutor(max_workers=len(PROBES)) as ex:
        futures = {
            ex.submit(_fetch, url, timeout): (name, url, kind)
            for name, url, kind in PROBES
        }
        for fut in as_completed(futures):
            name, url, kind = futures[fut]
            try:
                status, body = fut.result()
                if status == 200:
                    results[name] = _parse(kind, body)
                else:
                    results[name] = {"error": body, "status": status}
            except Exception as e:
                results[name] = {"error": str(e)}
    return results


def best_ip(data: dict) -> str:
    """Pick the IP that appears most often across probes."""
    candidates: list[str] = []
    for name, d in data.items():
        ip = None
        if isinstance(d, dict):
            ip = d.get("ip") or d.get("query")
        if ip and isinstance(ip, str) and ip.count(".") in (3,) and len(ip) <= 15:
            candidates.append(ip)
    if not candidates:
        # Cloudflare trace
        cf = data.get("cloudflare", {})
        if isinstance(cf, dict):
            ip = cf.get("ip")
            if ip:
                candidates.append(ip)
    if not candidates:
        return ""
    # Most common
    from collections import Counter
    return Counter(candidates).most_common(1)[0][0]


def format_text(data: dict) -> str:
    lines: list[str] = ["Public IP reconnaissance"]
    lines.append("=" * 50)
    ip = best_ip(data)
    lines.append(f"Most likely public IP: {ip or '?'}")
    lines.append("")
    for name, d in data.items():
        lines.append(f"## {name}")
        if isinstance(d, dict):
            if "error" in d:
                lines.append(f"   ERROR: {d['error']}")
            else:
                for k, v in d.items():
                    if k in ("readme", "_disclaimer"):
                        continue
                    lines.append(f"   {k}: {v}")
        else:
            lines.append(f"   {d}")
        lines.append("")
    return "\n".join(lines)


def main():
    p = argparse.ArgumentParser(description="Public IP / geo reconnaissance")
    p.add_argument("--json", action="store_true")
    p.add_argument("--quiet", action="store_true", help="Just print the best IP")
    p.add_argument("--timeout", type=float, default=5.0)
    args = p.parse_args()

    # UTF-8 stdout on Windows
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    data = collect(timeout=args.timeout)
    if args.quiet:
        print(best_ip(data))
        return
    if args.json:
        out = {
            "generated_at": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat(),
            "best_ip": best_ip(data),
            "probes": data,
        }
        print(json.dumps(out, indent=2, ensure_ascii=False))
    else:
        print(format_text(data))


if __name__ == "__main__":
    main()
