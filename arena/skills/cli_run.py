"""Skill runner execution command."""
from __future__ import annotations

from arena.skills.cli_common import *  # noqa: F401,F403

def run_skill(args) -> int:
    _fire_hook("pre_skill", getattr(args, "name", ""), {"args": getattr(args, "skill_args", [])})
    d = find_skill_dir(args.name)
    if not d:
        print(f"skill not found: {args.name}", file=sys.stderr)
        return 2

    manifest = {}
    mf = d / "manifest.json"
    if mf.exists():
        try:
            manifest = json.loads(mf.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            print(f"warning: manifest.json is invalid: {e}", file=sys.stderr)

    timeout = int(manifest.get("timeout", 300))
    if args.timeout:
        timeout = args.timeout

    run_sh = d / "run.sh"
    run_py = d / "run.py"
    if run_sh.exists():
        cmd = ["bash", str(run_sh), *args.skill_args]
    elif run_py.exists():
        cmd = [sys.executable, str(run_py), *args.skill_args]
    else:
        print(f"skill '{args.name}' has neither run.sh nor run.py", file=sys.stderr)
        return 2

    LOGS.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)
    env.setdefault("ARENA_AGENT_HOME", str(ROOT))
    env["SKILL_NAME"] = d.relative_to(SK).as_posix()
    env["SKILL_DIR"] = str(d)

    start = time.monotonic()
    rc = 0
    try:
        cp = subprocess.run(cmd, cwd=str(d), env=env, timeout=timeout)
        rc = cp.returncode
    except subprocess.TimeoutExpired:
        rc = 124
        print(f"\n[skill timeout after {timeout}s]", file=sys.stderr)
    except KeyboardInterrupt:
        rc = 130
        print("\n[skill interrupted]", file=sys.stderr)

    duration = round(time.monotonic() - start, 3)
    rec = {
        "ts": now_iso(),
        "skill": env["SKILL_NAME"],
        "args": args.skill_args,
        "exit": rc,
        "duration_sec": duration,
    }
    try:
        with LOG_FILE.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        try:
            LOG_FILE.chmod(0o600)
        except OSError:
            pass
    except OSError:
        pass
    _fire_hook("post_skill", getattr(args, "name", ""), {"args": getattr(args, "skill_args", [])}, rc)
    return rc
