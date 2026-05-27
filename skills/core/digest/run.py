#!/usr/bin/env python3
"""core/digest — compact platform snapshot for new Arena chats."""
from __future__ import annotations

import datetime as dt
import os
import socket
import subprocess
import sys
from pathlib import Path

ROOT = Path(os.environ.get("ARENA_AGENT_HOME", str(Path.home() / "arena-bridge"))).expanduser()
AGENTCTL = ROOT / "bin" / "agentctl"


def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def sh(cmd: list[str], timeout: int = 15) -> str:
    try:
        cp = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        out = cp.stdout or ""
        if cp.stderr and not out:
            out = cp.stderr
        return out.rstrip()
    except Exception as e:
        return f"(error: {e!r})"


def tail_lines(text: str, n: int) -> str:
    return "\n".join(text.splitlines()[-n:])


def head_lines(text: str, n: int) -> str:
    return "\n".join(text.splitlines()[:n])


def safe_listdir(p: Path, n: int) -> list[str]:
    if not p.is_dir():
        return []
    try:
        items = sorted(p.iterdir(), key=lambda x: x.stat().st_mtime, reverse=True)
        return [x.name for x in items[:n] if not x.name.startswith(".")]
    except OSError:
        return []


def build() -> str:
    parts: list[str] = []
    p = parts.append

    p(f"# Arena Agent — digest  ({now_iso()}  host:{socket.gethostname()})\n")

    p("## Health (short)")
    bridge_health = sh(["curl", "-fsS", "--max-time", "3",
                        "http://127.0.0.1:8765/health"])
    p("```text")
    p(head_lines(bridge_health, 10) or "(no response)")
    p("```\n")

    p("## Services")
    svc = sh(["systemctl", "--user", "is-active",
              "arena-local-bridge.service", "arena-task-runner.service"])
    p("```text")
    p(svc)
    p("```\n")

    proj = sh([str(AGENTCTL), "project-current"], timeout=10)
    if proj and "not found" not in proj.lower():
        p(f"## Current project: `{proj.splitlines()[0]}`\n")

    p("## Recent memory (last 8)")
    mem = sh([str(AGENTCTL), "memory-recall"], timeout=15)
    p("```text")
    p(tail_lines(mem, 8) or "(empty)")
    p("```\n")

    last = sh([str(AGENTCTL), "task-last"], timeout=10)
    if last.strip():
        p("## Last task")
        p("```text")
        p(head_lines(last, 6))
        p("```\n")

    reps = safe_listdir(ROOT / "reports", 5)
    if reps:
        p("## Recent reports")
        for r in reps:
            p(f"- {r}")
        p("")

    sess = safe_listdir(ROOT / "memory" / "sessions", 10)
    sess = [s for s in sess if s.endswith(".jsonl")]
    if sess:
        p("## Recent chat sessions")
        for s in sess:
            p(f"- {s}")
        p("")

    p("## Command groups (top-level)")
    p("```text")
    p("chat        chat / chat-list / chat-tail / chat-append")
    p("project     project-new|-use|-current|-list|-status|-report|-git-init|"
      "-commit|-log|-branch|-issue-new|-issues|-issue-close|-attach-report")
    p("task        tasks / task-submit / task-run / task-watch / task-show / "
      "task-last / task-retry / task-clean")
    p("browser     browser-smoke / browser-report / readability / screenshot / "
      "page-dump / browser-fingerprint / browser-metadata")
    p("recon       ip / http / headers / robots / sitemap / tech-detect / "
      "dns-check / tls-check / recon-domain / recon-report")
    p("memory      memory-remember / memory-recall")
    p("skill       skill list|show|run|new|path  (also: skill-list / skill-show)")
    p("reports     reports / report-index / report-latest / report-status")
    p("admin       doctor / status / services / selftest / inventory / tree / "
      "harden-perms / service-* / funnel / py / pip-freeze / tools-install / "
      "backup / backups / audit-tail|stats|rotate / recovery-update|-print")
    p("```")
    p("")
    return "\n".join(parts)


def main() -> int:
    out_path = Path(sys.argv[1]).expanduser() if len(sys.argv) > 1 else None
    if out_path is None:
        rep = ROOT / "reports"
        rep.mkdir(parents=True, exist_ok=True)
        stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        out_path = rep / f"digest-{stamp}.md"

    content = build()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(content, encoding="utf-8")
    try:
        out_path.chmod(0o600)
    except OSError:
        pass
    print(out_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
