"""agentctl extras action commands."""
from __future__ import annotations

from arena.agentctl_extras.common import *  # noqa: F401,F403

def play_notification_sound():
    try:
        import platform
        import sys
        if platform.system() == "Windows":
            import winsound
            winsound.MessageBeep(winsound.MB_ICONASTERISK)
        elif platform.system() == "Darwin":
            # v4.42.0: was ``os.system(...)`` which spawns a shell
            # and could be tainted by future refactors that
            # accidentally interpolate a variable into the string.
            # Switched to argv-form subprocess.run for the same
            # reason the rest of the codebase avoids os.system.
            import subprocess
            subprocess.run(["osascript", "-e", "beep"], check=False)
        else:
            sys.stdout.write("\a")
            sys.stdout.flush()
    except Exception:
        pass

def cmd_do(args: list[str]) -> int:
    if not args:
        print("usage: agentctl do '<shell command>'", file=sys.stderr)
        return 2
    cmd_str = args[0] if len(args) == 1 else " ".join(args)
    python = shutil.which("python3") or shutil.which("python") or sys.executable
    cp = subprocess.run([python, str(AGENTCTL), "task-submit", cmd_str], capture_output=True, text=True)
    if cp.returncode != 0:
        print(f"Error submitting task: {cp.stderr}", file=sys.stderr)
        return cp.returncode
    
    # FIXED (v4.3): Extract base filename as task_id to avoid path separator / vs \ conflicts on Windows!
    task_path = cp.stdout.strip()
    task_id = os.path.basename(task_path).replace(".json", "")
    print(f"submitted: {task_id}")
    
    # Wait for result
    for _ in range(600):
        time.sleep(1)
        cp2 = subprocess.run([python, str(AGENTCTL), "task", "show", task_id], capture_output=True, text=True)
        if cp2.returncode == 0:
            try:
                task = json.loads(cp2.stdout)
                if task.get("state") in ["done", "failed"]:
                    print(task.get("stdout", ""))
                    if task.get("stderr"):
                        print(task.get("stderr"), file=sys.stderr)
                    try: play_notification_sound()
                    except Exception: pass
                    return 0 if task.get("state") == "done" else 1
            except Exception:
                pass
    print("timeout waiting for task execution", file=sys.stderr)
    return 1

def cmd_tail(args: list[str]) -> int:
    kind = args[0] if args else "audit"
    n = int(args[1]) if len(args) > 1 else 20
    if kind == "audit":
        p = ROOT / "logs" / "audit.jsonl"
        if not p.exists():
            p = Path.home() / "arena-bridge" / "audit.jsonl"
    else:
        p = ROOT / "logs" / f"{kind}.jsonl"
    
    if not p.exists():
        print(f"log file not found: {p}", file=sys.stderr)
        return 1
    
    # Simple cross-platform tail
    try:
        lines = p.read_text(encoding="utf-8", errors="ignore").splitlines()
        for line in lines[-n:]:
            print(line)
    except Exception as e:
        print(f"Error reading log: {e}", file=sys.stderr)
        return 1
    return 0

def cmd_find(args: list[str]) -> int:
    if not args:
        print("usage: agentctl find <pattern>", file=sys.stderr)
        return 2
    pattern = args[0].lower()
    count = 0
    # Search in sessions, reports, skills
    for folder in [ROOT / "memory" / "sessions", ROOT / "reports"]:
        if not folder.exists(): continue
        for fp in folder.glob("**/*"):
            if fp.is_file() and fp.suffix in [".json", ".jsonl", ".txt", ".md"]:
                try:
                    content = fp.read_text(encoding="utf-8", errors="ignore")
                    if pattern in content.lower() or pattern in fp.name.lower():
                        print(f"Match found in: {fp.relative_to(ROOT)}")
                        count += 1
                except Exception:
                    pass
    print(f"Total matches: {count}")
    return 0

def cmd_remember(args: list[str]) -> int:
    if len(args) < 2:
        print("usage: agentctl remember <key> <value> [--tags tag1,tag2]", file=sys.stderr)
        return 2
    key = args[0]
    val = args[1]
    tags = []
    if "--tags" in args:
        idx = args.index("--tags")
        if idx + 1 < len(args):
            tags = args[idx+1].split(",")
    
    facts_file = ROOT / "memory" / "facts.jsonl"
    facts_file.parent.mkdir(parents=True, exist_ok=True)
    fact = {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "key": key,
        "val": val,
        "tags": tags
    }
    try:
        with open(facts_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(fact, ensure_ascii=False) + "\n")
        print(f"[OK] Remembered fact: {key}")
    except Exception as e:
        print(f"Error writing fact: {e}", file=sys.stderr)
        return 1
    return 0
