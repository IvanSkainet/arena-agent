"""Interactive chat REPL loop."""
from __future__ import annotations

from arena.chat_cli.common import *  # noqa: F401,F403
from arena.chat_cli.commands import *  # noqa: F401,F403

def repl(session_path: Path, mode: str) -> int:
    proj = current_project() or "-"
    print(f"arena-bridge chat — session: {session_path.name}")
    print(f"mode: {mode}   project: {proj}")
    print("type /help for commands, /exit to quit")

    while True:
        proj = current_project() or "-"
        try:
            line = input(f"[{mode}|{proj}] > ")
        except (EOFError, KeyboardInterrupt):
            print()
            write_event(session_path, "system", "note", "session ended")
            return 0
        line = line.rstrip()
        if not line:
            continue

        if not line.startswith("/"):
            write_event(session_path, "user", "message", line)
            print("(logged — remote agent will see it via bridge)")
            continue

        parts = line.split(None, 1)
        cmd = parts[0].lower()
        arg = parts[1] if len(parts) > 1 else ""
        write_event(session_path, "user", "slash", line)

        out, code = "", 0
        if cmd in ("/exit", "/quit"):
            write_event(session_path, "system", "note", "session ended")
            return 0
        elif cmd == "/help":
            print_help()
            continue
        elif cmd == "/mode":
            if arg.strip() in ("safe", "edit", "full"):
                mode = arg.strip()
                write_event(session_path, "system", "note", f"mode={mode}")
                out = f"mode set to {mode}"
            else:
                out, code = "usage: /mode safe|edit|full", 2
        elif cmd == "/project":
            if arg.strip():
                code, out = run_agentctl(["project-use", arg.strip()])
            else:
                code, out = run_agentctl(["project-current"])
        elif cmd == "/web":
            code, out = cmd_web(arg)
        elif cmd == "/recon":
            code, out = cmd_recon(arg)
        elif cmd == "/run":
            code, out = cmd_run(arg, mode)
        elif cmd == "/task":
            if arg.strip():
                code, out = run_agentctl(["task-submit", arg])
            else:
                code, out = run_agentctl(["tasks"])
        elif cmd == "/remember":
            if arg.strip():
                code, out = run_agentctl(["memory-remember", "chat", arg,
                                          "--tags", "chat", "repl"])
            else:
                out, code = "usage: /remember <text>", 2
        elif cmd == "/recall":
            code, out = run_agentctl(["memory-recall", arg] if arg.strip()
                                     else ["memory-recall"])
        elif cmd == "/skill":
            if arg.strip():
                code, out = run_agentctl(["skill-show", *shlex.split(arg)])
            else:
                code, out = run_agentctl(["skill-list"])
        elif cmd == "/context":
            out = cmd_context()
        elif cmd == "/tail":
            try:
                n = int(arg.strip()) if arg.strip() else 20
            except ValueError:
                n = 20
            lines_all = session_path.read_text(encoding="utf-8").splitlines()
            out = "\n".join(lines_all[-n:])
        elif cmd == "/status":
            code, out = run_agentctl(["status"])
            out = "\n".join(out.splitlines()[:40])
        elif cmd == "/agent-tail":
            try:
                n = int(arg.strip()) if arg.strip() else 5
            except ValueError:
                n = 5
            import json as _json
            msgs = []
            for ln in session_path.read_text(encoding="utf-8").splitlines():
                try:
                    rec = _json.loads(ln)
                except Exception:
                    continue
                if rec.get("role") == "agent":
                    msgs.append(rec)
            tail = msgs[-n:]
            if not tail:
                out = "(no agent messages yet)"
            else:
                out = (chr(10)+chr(10)).join(f"[{m.get('ts','?')}] {m.get('content','')}" for m in tail)
        elif cmd == "/wait-agent":
            try:
                secs = int(arg.strip()) if arg.strip() else 120
            except ValueError:
                secs = 120
            import json as _json, time as _time
            start_size = session_path.stat().st_size
            deadline = _time.monotonic() + secs
            found = None
            print(f"(waiting up to {secs}s for an agent message... Ctrl-C to cancel)")
            try:
                while _time.monotonic() < deadline:
                    cur = session_path.stat().st_size
                    if cur > start_size:
                        # scan new tail
                        with session_path.open("r", encoding="utf-8") as f:
                            f.seek(start_size)
                            for ln in f:
                                try:
                                    rec = _json.loads(ln)
                                except Exception:
                                    continue
                                if rec.get("role") == "agent":
                                    found = rec
                                    break
                        start_size = cur
                        if found:
                            break
                    _time.sleep(1.0)
            except KeyboardInterrupt:
                out, code = "(wait cancelled)", 130
                write_event(session_path, "tool", "result", out, exit=code, slash=cmd)
                print(out)
                continue
            if found:
                out = f"[{found.get('ts','?')}] {found.get('content','')}"
            else:
                out, code = "(timeout — no agent reply)", 124
        else:
            out, code = f"unknown command: {cmd} (try /help)", 2

        write_event(session_path, "tool", "result", out, exit=code, slash=cmd)
        print(out if out else f"(exit {code})")
