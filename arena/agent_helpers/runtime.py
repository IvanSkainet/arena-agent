"""Agent helper runtime operations."""
from __future__ import annotations

import os

from arena.agent_helpers.files import FACTS, Path, json, now_iso, subprocess
from arena.file_lock import journal_lock


def run_local(cmd: str | list[str], timeout: int = 60,
              cwd: Path | str | None = None) -> tuple[int, str]:
    if isinstance(cmd, str):
        cp = subprocess.run(cmd, shell=True, capture_output=True,  # nosec B602,B604 -- run_local's str-form input is only invoked by operator-side CLI tooling (agentctl), never by an HTTP handler; the list-form (safe) is used for programmatic paths.  # nosemgrep: subprocess-shell-true -- legitimate CLI-side helper (see bandit B602 nosec on the same line for the specific rationale)
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
    for raw_line in FACTS.read_bytes().split(b"\n"):
        try:
            obj = json.loads(raw_line.decode("utf-8"))
        except (UnicodeError, ValueError):
            continue
        if not isinstance(obj, dict):
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
    FACTS.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    FACTS.parent.chmod(0o700)
    rec = {"ts": now_iso(), "type": "fact",
           "key": key, "value": value,
           "tags": tags or []}
    # Preserve an unfinished tail but separate it from the new record. Without
    # this newline, one interrupted writer causes the next successful `put`
    # to be concatenated with invalid JSON and silently skipped by the importer.
    with journal_lock(FACTS.with_name(FACTS.name + ".append-lock")):
        fd = os.open(FACTS, os.O_CREAT | os.O_RDWR | os.O_APPEND, 0o600)
        with os.fdopen(fd, "a+b") as f:
            f.seek(0, 2)
            size = f.tell()
            separator = b""
            if size:
                f.seek(-1, 2)
                if f.read(1) != b"\n":
                    separator = b"\n"
            encoded = (json.dumps(rec, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8")
            f.write(separator + encoded)
    try:
        FACTS.chmod(0o600)
    except OSError:
        pass
