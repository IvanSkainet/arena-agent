"""CLI for scripts/agent_helpers.py."""
from __future__ import annotations

from arena.agent_helpers.runtime import *  # noqa: F401,F403

def cli_self_check(_args) -> int:
    issues = []
    # 1. ROOT exists
    if not ROOT.is_dir():
        issues.append(f"ROOT missing: {ROOT}")
    # 2. agentctl is executable
    a = ROOT / "bin" / "agentctl"
    if not a.is_file() or not os.access(a, os.X_OK):
        issues.append(f"agentctl not executable: {a}")
    else:
        ok, msg = verify_bash(a)
        if not ok:
            issues.append(f"agentctl bash -n failed: {msg}")
    # 3. system python3 works
    if not shutil.which("python3"):
        issues.append("python3 not found in PATH")
    # 4. critical python scripts import
    for name in ("memory.py", "task_runner.py", "chat.py",
                 "chat_append.py", "skill_runner.py", "recovery_prompt.py",
                 "agent_helpers.py"):
        path = ROOT / "scripts" / name
        if not path.exists():
            issues.append(f"missing script: {name}")
            continue
        ok, msg = verify_python(path)
        if not ok:
            issues.append(f"{name}: {msg}")
    # 5. services
    cp = subprocess.run(["systemctl", "--user", "is-active",
                         "arena-bridge.service",
                         "arena-task-runner.service"],
                        capture_output=True, text=True)
    states = cp.stdout.strip().splitlines()
    if len(states) >= 1 and states[0] != "active":
        issues.append(f"arena-bridge.service: {states[0]}")
    if len(states) >= 2 and states[1] != "active":
        issues.append(f"arena-task-runner.service: {states[1]}")
    # 6. session dir
    sd = ROOT / "memory" / "sessions"
    if not sd.is_dir():
        issues.append(f"sessions dir missing: {sd}")
    # report
    if not issues:
        print("OK — all self-checks passed")
        return 0
    print(f"FAIL — {len(issues)} issue(s):")
    for i in issues:
        print(f"  - {i}")
    return 1

def cli_facts(args) -> int:
    rows = load_facts(args.query or "", args.limit)
    if not rows:
        print("(no facts)")
        return 0
    for obj in rows:
        tags = ",".join(obj.get("tags", []) or []) or "-"
        print(f"[{obj.get('ts')}] {obj.get('key')} [{tags}] {obj.get('value')}")
    return 0

def cli_put(args) -> int:
    tags = [t for t in args.tags.split(",") if t] if args.tags else []
    put_fact(args.key, " ".join(args.value), tags=tags)
    print("ok")
    return 0

def main() -> int:
    ap = argparse.ArgumentParser(prog="agent_helpers")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("self-check").set_defaults(func=cli_self_check)
    s = sub.add_parser("facts")
    s.add_argument("query", nargs="?", default="")
    s.add_argument("--limit", type=int, default=20)
    s.set_defaults(func=cli_facts)
    s = sub.add_parser("put")
    s.add_argument("key")
    s.add_argument("tags", help="comma-separated tags, or '-' for none")
    s.add_argument("value", nargs=argparse.REMAINDER)
    s.set_defaults(func=cli_put)
    args = ap.parse_args()
    return args.func(args)
