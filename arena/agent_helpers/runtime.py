"""Agent helper runtime operations."""
from __future__ import annotations

from arena.agent_helpers.files import *  # noqa: F401,F403

def run_local(cmd: str | list[str], timeout: int = 60,
              cwd: Path | str | None = None) -> tuple[int, str]:
    if isinstance(cmd, str):
        cp = subprocess.run(cmd, shell=True, capture_output=True,  # nosec B602 -- run_local's str-form input is only invoked by operator-side CLI tooling (agentctl), never by an HTTP handler; the list-form (safe) is used for programmatic paths.
                            text=True, timeout=timeout,
                            cwd=str(cwd) if cwd else None)
    else:
        cp = subprocess.run(cmd, capture_output=True, text=True,
                            timeout=timeout,
                            cwd=str(cwd) if cwd else None)
    out = (cp.stdout or "")
    if cp.stderr:
        out += ("\n" if out else "") + cp.stderr
    return cp.returncode, out.rstrip()

def load_facts(query: str = "", limit: int = 50) -> list[dict]:
    if not FACTS.exists():
        return []
    q = query.lower()
    out = []
    for ln in FACTS.read_text(encoding="utf-8").splitlines():
        try:
            obj = json.loads(ln)
        except Exception:
            continue
        if q:
            hay = (str(obj.get("key", "")) + " "
                   + str(obj.get("value", "")) + " "
                   + " ".join(obj.get("tags", []) or [])).lower()
            if q not in hay:
                continue
        out.append(obj)
    return out[-limit:]

def put_fact(key: str, value: str, tags: list[str] | None = None) -> None:
    FACTS.parent.mkdir(parents=True, exist_ok=True)
    rec = {"ts": now_iso(), "type": "fact",
           "key": key, "value": value,
           "tags": tags or []}
    with FACTS.open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False, sort_keys=True) + "\n")
    try:
        FACTS.chmod(0o600)
    except OSError:
        pass
