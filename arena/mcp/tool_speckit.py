"""v4.60.19 - spec-kit MCP tool for Arena Unified Bridge.

Wraps the `specify` CLI (github/spec-kit) so that scenarios and
agents can drive the spec-driven workflow through the bridge.

This is a *consumer* of spec-kit, not a reimplementation. The CLI
remains the source of truth; we just expose it via the MCP surface
so that scenarios can call `speccy.run` like any other bridge tool.

Design rules (per AGENTS.md / handoff):
  * If the CLI is not on PATH, the tool returns an `isError` dict
    with a clear message — never crashes, never hangs.
  * All subprocess calls have an explicit timeout (default 60s).
  * No TTY assumptions. We never pass `stdin=tty`; we use a pipe
    so the call is fully non-interactive. The CLI's TUI prompts
    will fail loudly in this mode, which is the desired behaviour
    (we want non-interactive use only).
  * This tool is **optional**: the bridge runs fine without
    `specify` on PATH. The optional install is wired in
    `install.bat` / `install.sh` behind a `[y/N]` prompt.

Tool name (as registered in `mcp/tool_registry.py`):
  speccy.run

Arguments:
  args: list[str]        # passthrough to the specify CLI, e.g.
                          # ["specify", "check"] or
                          # ["specify", "workflow", "list"]
  cwd: str | None = None # optional working directory (defaults to
                          # the scenario's cwd)
  timeout: int = 60      # seconds

Returns (success):
  {"ok": True, "stdout": str, "stderr": str, "exit_code": int,
   "elapsed_sec": float, "cli": str}

Returns (failure):
  {"isError": True, "content": [{"type": "text",
    "text": "ERROR: <reason>"}]}
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

# Resolve the path to the `specify` CLI. The convention is to look it
# up via shutil.which; if absent, we return an `isError` envelope
# immediately (do NOT crash, do NOT block).
_CLI_NAME = "specify"


def _isError(msg: str) -> dict:
    """MCP-style error envelope."""
    return {
        "isError": True,
        "content": [{"type": "text", "text": f"ERROR: {msg}"}],
    }


def _success(stdout: str, stderr: str, exit_code: int, elapsed: float, cli: str) -> dict:
    return {
        "ok": True,
        "stdout": stdout,
        "stderr": stderr,
        "exit_code": exit_code,
        "elapsed_sec": round(elapsed, 3),
        "cli": cli,
    }


def run_speccy(args: list[str], cwd: str | None = None, timeout: int = 60) -> dict:
    """Run `specify <args>` and return stdout/stderr/exit_code.

    Non-interactive: the CLI gets no TTY, so any prompt-driven flow
    will fail with an error message rather than hang. Callers are
    expected to pass non-interactive flags (e.g. `specify check`,
    `specify self check`, `specify workflow list`).
    """
    cli_path = shutil.which(_CLI_NAME)
    if not cli_path:
        return _isError(
            f"`{_CLI_NAME}` CLI not on PATH. Install with: "
            f"`uv tool install specify-cli` (or skip if not needed)."
        )

    if not isinstance(args, list) or not all(isinstance(a, str) for a in args):
        return _isError("`args` must be a list[str].")

    full_cmd = [cli_path, *args]
    env = os.environ.copy()
    # Force non-interactive: no TTY. The CLI uses rich + readchar
    # which will fail gracefully in this mode.
    env["NO_COLOR"] = "1"  # less noise in logs
    env["PYTHONUNBUFFERED"] = "1"
    # Some readchar-driven prompts expect stdin to be a TTY. Setting
    # CI=true makes several well-behaved CLIs (e.g. pip, git) skip
    # prompts. It is also a hint to the CLI that we are in a script.
    env.setdefault("CI", "true")

    t0 = time.monotonic()
    try:
        proc = subprocess.run(
            full_cmd,
            cwd=cwd,
            env=env,
            stdin=subprocess.DEVNULL,  # never block on a TTY prompt
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",          # CLI may emit unicode in banners;
                                        # never crash on decode errors.
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as e:
        return _isError(
            f"`{_CLI_NAME} {' '.join(args)}` timed out after {timeout}s."
        )
    except FileNotFoundError as e:
        return _isError(f"failed to launch `{_CLI_NAME}`: {e}")
    except Exception as e:
        return _isError(f"unexpected error running `{_CLI_NAME}`: {e!r}")
    elapsed = time.monotonic() - t0

    # The CLI's pretty-printed output includes ANSI codes; we strip
    # them so logs and scenario result files are clean.
    def _strip_ansi(s: str) -> str:
        import re
        return re.sub(r"\x1b\[[0-9;]*m", "", s)

    return _success(
        stdout=_strip_ansi(proc.stdout or ""),
        stderr=_strip_ansi(proc.stderr or ""),
        exit_code=proc.returncode,
        elapsed=elapsed,
        cli=cli_path,
    )


# ---------------------------------------------------------------------------
# MCP integration glue
# ---------------------------------------------------------------------------
# The `mcp/` registry discovers this module by looking for functions
# named `handle_<tool_name>`. Our tool name is `speccy.run`, but MCP
# tool names use dots as separators and we want a single dispatch
# function. We register a single function `handle_speccy` that reads
# the `tool` arg from the dispatch (e.g. `speccy.run` or `speccy.check`)
# and routes to the right internal function. The dispatcher convention
# in this repo is documented in `mcp/tool_registry.py`.


def handle_speccy(name: str, args: dict, *, ctx) -> dict:
    """Single dispatch entry for all `speccy.*` MCP tools.

    Current surface:
      * `speccy.run`      — generic CLI passthrough (args list)
      * `speccy.check`    — sugar for `specify check`
      * `speccy.version`  — sugar for `specify version`
    """
    if name == "speccy.run":
        return run_speccy(
            args=args.get("args", []),
            cwd=args.get("cwd"),
            timeout=int(args.get("timeout", 60)),
        )
    if name == "speccy.check":
        return run_speccy(args=["check"], cwd=args.get("cwd"),
                          timeout=int(args.get("timeout", 30)))
    if name == "speccy.version":
        return run_speccy(args=["--version"], cwd=args.get("cwd"),
                          timeout=15)
    return _isError(f"unknown speccy tool: {name!r}")


# ---------------------------------------------------------------------------
# Ad-hoc CLI for local smoke testing
# ---------------------------------------------------------------------------
def _smoke() -> int:
    """Run a couple of in-process checks (no Tailscale / no bridge)."""
    import json

    def _safe_print(s: str) -> None:
        """Print string safely even when stdout is cp1251 (Windows bridge log).

        We replace any non-cp1251 codepoints with `?` so the bridge
        audit log stays valid UTF-8-or-cp1251, never crashes. The
        smoke test runs in non-TTY subprocesses where Unicode
        banners from the CLI are common; this preserves the ASCII
        parts (the actual signal).
        """
        enc = sys.stdout.encoding or "utf-8"
        sys.stdout.write(s.encode(enc, errors="replace").decode(enc, errors="replace"))
        sys.stdout.write("\n")

    # 1) version probe.
    r = run_speccy(args=["--version"], timeout=15)
    _safe_print("[1] version: ok=" + str(r.get("ok")) + " cli=" + str(r.get("cli", "")))
    _safe_print("    stdout=" + str(r.get("stdout", ""))[:200])
    if not r.get("ok") or "specify " not in r.get("stdout", ""):
        _safe_print("[1] FAIL: version probe did not return the expected string")
        return 1

    # 2) unknown subcommand — should fail fast with non-zero exit.
    r = run_speccy(args=["this-is-not-a-real-subcommand"], timeout=15)
    _safe_print("[2] unknown subcommand: ok=" + str(r.get("ok")) + " exit_code=" + str(r.get("exit_code")))
    if r.get("ok") and r.get("exit_code") == 0:
        _safe_print("[2] FAIL: unknown subcommand should have non-zero exit")
        return 2

    # 3) handle_speccy dispatcher.
    r = handle_speccy("speccy.version", {}, ctx=None)
    _safe_print("[3] dispatcher speccy.version: ok=" + str(r.get("ok")))
    if not r.get("ok"):
        _safe_print("[3] FAIL: dispatcher speccy.version failed")
        return 3

    r = handle_speccy("speccy.bogus", {}, ctx=None)
    _safe_print("[4] unknown tool name: isError=" + str(r.get("isError")))
    if not r.get("isError"):
        _safe_print("[4] FAIL: unknown tool should return isError")
        return 4

    _safe_print("All smoke checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(_smoke())
