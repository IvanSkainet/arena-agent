"""agentctl extras MCP/beep integration commands."""
from __future__ import annotations

from typing import Any

from arena.agentctl_extras.common import ROOT, json, shutil, subprocess, sys


def cmd_mcp_install(args: list[str]) -> int:
    if not args:
        print("usage: agentctl mcp install <npm-package-or-alias>", file=sys.stderr)
        print("examples:", file=sys.stderr)
        print("  agentctl mcp install desktop-commander", file=sys.stderr)
        print("  agentctl mcp install @modelcontextprotocol/filesystem", file=sys.stderr)
        return 2
    alias = args[0]
    # v4.165.0 (bug #69): every one of the four built-in aliases pointed at
    # a package that does not exist. Checked against the live registry:
    # @anthropic-ai/desktop-commander, @modelcontextprotocol/filesystem,
    # /sqlite and /fetch all return 404. The real servers carry a
    # `server-` prefix, and desktop-commander is published by a different
    # scope entirely.
    #
    # `@anthropic-ai/desktop-commander` is the worst of the four: it names
    # an unclaimed package in a scope this project does not control, so the
    # command was one registration away from installing someone else's code
    # as root-ish tooling. Only names verified present are shipped now, and
    # `verify_known_aliases()` below keeps the list honest.
    pkg = known_aliases().get(alias, alias)
    mcp_dir = ROOT / "mcp"
    mcp_dir.mkdir(parents=True, exist_ok=True)
    cfg_path = mcp_dir / "mcp.json"
    cfg = json.loads(cfg_path.read_text(encoding="utf-8")) if cfg_path.exists() else {"mcpServers": {}}
    if "mcpServers" not in cfg:
        cfg["mcpServers"] = {}

    # v4.165.0 (bug #69): install FIRST, register second. The old order
    # wrote the entry, then attempted the install, then returned 0 no
    # matter what -- so `agentctl mcp install <typo>` printed "[OK]
    # Registered", printed a warning nobody scripts against, exited
    # successfully, and left mcp.json pointing at a package that does not
    # exist. The bridge then tried to launch it on every start.
    #
    # The consolation message made it worse: "npx will download the
    # package on first run automatically" is only true when the package
    # exists. For a 404 it is a promise that cannot be kept.
    npm = shutil.which("npm")
    if npm is None:
        # The old test was `if npm or npx`, but the call is always `npm` --
        # so on a machine with npx and no npm (corepack, bun-first setups,
        # trimmed images) it raised FileNotFoundError out of a CLI command.
        print("[ERROR] npm not found. Install Node.js from https://nodejs.org/ "
              "first.", file=sys.stderr)
        return 3

    print(f"[INFO] Verifying '{pkg}' via npm...")
    try:
        r = subprocess.run(  # nosec B603,B607 -- fixed argv, no shell
            [npm, "install", "-g", pkg],
            capture_output=True, text=True, timeout=300,
        )
    except subprocess.TimeoutExpired:
        print(f"[ERROR] npm install -g {pkg} timed out after 300s.",
              file=sys.stderr)
        return 4
    except OSError as e:
        print(f"[ERROR] could not run npm: {e}", file=sys.stderr)
        return 3

    if r.returncode != 0:
        detail = (r.stderr or r.stdout or "").strip()[:300]
        print(f"[ERROR] npm install -g {pkg} failed (exit {r.returncode}).",
              file=sys.stderr)
        if detail:
            print(f"        {detail}", file=sys.stderr)
        if "E404" in detail or "404 Not Found" in detail:
            print(f"        '{pkg}' is not published under that name. Check "
                  f"the spelling, or pass the full package name.",
                  file=sys.stderr)
        print("[INFO] mcp.json was NOT modified.", file=sys.stderr)
        return 1

    print("[OK] Package ready.")
    if alias not in cfg["mcpServers"]:
        cfg["mcpServers"][alias] = {"command": "npx", "args": ["-y", pkg], "env": {}}
        cfg_path.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"[OK] Registered '{alias}' -> npx -y {pkg} in {cfg_path}")
    else:
        print(f"'{alias}' already registered in mcp.json")
    print("[INFO] Restart MCP services to pick up new servers:")
    print("       Windows:  Start-ScheduledTask -TaskName ArenaMcpStream; Start-ScheduledTask -TaskName ArenaMcpWs")
    print("       Linux:    systemctl --user restart arena-mcp-stream.service arena-mcp-ws.service")
    return 0


def known_aliases() -> dict[str, str]:
    """The built-in alias -> npm package map, exposed for verification.

    Kept as a function rather than a module constant so the gate that
    checks these names against the live registry has one obvious thing to
    import, and so a future caller cannot mutate the table in place.
    """
    return {
        "desktop-commander": "@wonderwhy-er/desktop-commander",
        "filesystem": "@modelcontextprotocol/server-filesystem",
        "memory": "@modelcontextprotocol/server-memory",
        "everything": "@modelcontextprotocol/server-everything",
    }

def cmd_beep(args: list[str]) -> int:
    try:
        import platform
        import sys
        import time

        beep_type = "success"
        if "--type" in args:
            idx = args.index("--type")
            if idx + 1 < len(args):
                beep_type = args[idx+1].lower()

        custom_freq = None
        if "--frequency" in args:
            idx = args.index("--frequency")
            if idx + 1 < len(args):
                try:
                    custom_freq = int(args[idx+1])
                except Exception:
                    pass

        custom_dur = None
        if "--duration" in args:
            idx = args.index("--duration")
            if idx + 1 < len(args):
                try:
                    custom_dur = int(args[idx+1])
                except Exception:
                    pass

        if platform.system() == "Windows":
            # Windows-only stdlib module: on a Linux checkout the checker sees
            # the stub as empty, so every winsound.Beep below reads as a
            # missing attribute. The Any alias keeps the guarded branch quiet
            # without claiming the module is portable.
            import winsound as _winsound_mod
            winsound: Any = _winsound_mod
            if custom_freq and custom_dur:
                winsound.Beep(custom_freq, custom_dur)
            else:
                if beep_type == "error":
                    winsound.Beep(330, 250)
                    time.sleep(0.05)
                    winsound.Beep(262, 400)
                elif beep_type == "warning":
                    for _ in range(3):
                        winsound.Beep(440, 150)
                        time.sleep(0.05)
                elif beep_type == "attention":
                    winsound.Beep(1000, 100)
                    time.sleep(0.05)
                    winsound.Beep(1000, 100)
                elif beep_type == "melody":
                    winsound.Beep(523, 120)
                    winsound.Beep(659, 120)
                    winsound.Beep(784, 150)
                else:
                    # success (happy double beep)
                    winsound.Beep(523, 120)
                    time.sleep(0.05)
                    winsound.Beep(659, 150)
        elif platform.system() == "Darwin":
            # v4.42.0: switched from os.system() -- see the same
            # change in arena/agentctl_extras/actions.py for the
            # rationale (no-shell subprocess.run is refactor-safe).
            import subprocess
            subprocess.run(['osascript', '-e', 'beep'], check=False)
        else:
            sys.stdout.write("\a")
            sys.stdout.flush()
        print(f"[OK] Played {beep_type} sound notification.")
        return 0
    except Exception as e:
        print(f"Error playing beep: {e}", file=sys.stderr)
        return 1
