"""Long-running Code Workbench sessions (v4.116.0 MVP)."""
from __future__ import annotations

import json
import queue
import subprocess
import sys
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from arena.autonomy import posture as _posture
from arena.autonomy.runner import _resolve_runtime, _resolve_win32_runtime, _scrub_env
from arena.workbench.runtimes import home

_WORKER = r'''
import contextlib, io, json, sys, traceback
_ns = {"__name__": "__arena_session__"}
for line in sys.stdin:
    try:
        msg = json.loads(line)
        code = msg.get("code", "")
        out = io.StringIO(); err = io.StringIO()
        payload = {"ok": True, "stdout": "", "stderr": ""}
        try:
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                exec(code, _ns, _ns)
        except Exception as e:
            payload["ok"] = False
            payload["error"] = f"{type(e).__name__}: {e}"
            payload["traceback"] = traceback.format_exc(limit=8)
        payload["stdout"] = out.getvalue()
        payload["stderr"] = err.getvalue()
    except Exception as e:
        payload = {"ok": False, "error": f"worker protocol error: {type(e).__name__}: {e}"}
    sys.stdout.write(json.dumps(payload, ensure_ascii=False) + "\n")
    sys.stdout.flush()
'''


@dataclass
class Session:
    id: str
    name: str
    lang: str
    proc: subprocess.Popen
    cwd: Path
    started_at: float = field(default_factory=time.time)
    last_used_at: float = field(default_factory=time.time)
    posture: dict[str, Any] = field(default_factory=dict)
    _q: queue.Queue[str | None] = field(default_factory=queue.Queue)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def alive(self) -> bool:
        return self.proc.poll() is None


_SESSIONS: dict[str, Session] = {}
_SESSIONS_LOCK = threading.Lock()


def _sessions_root() -> Path:
    p = home() / "code-sessions"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _reader(sess: Session) -> None:
    try:
        assert sess.proc.stdout is not None
        for line in sess.proc.stdout:
            sess._q.put(line)
    except Exception:
        pass
    finally:
        sess._q.put(None)


def _resolve_python(lang: str) -> str | None:
    if sys.platform == "win32":
        return _resolve_win32_runtime(lang)
    return _resolve_runtime(lang)


def _cleanup_dead() -> None:
    with _SESSIONS_LOCK:
        for sid, sess in list(_SESSIONS.items()):
            if not sess.alive():
                _SESSIONS.pop(sid, None)


def start(*, lang: str = "python3", name: str = "", cwd: str | None = None) -> dict[str, Any]:
    _cleanup_dead()
    active = _posture.load_posture()
    if active.get("sandbox") != "off":
        return {"ok": False, "error": "code_session.start currently requires operator posture sandbox=off (MVP host session). Start a new session after selecting an explicit host/off posture."}
    if lang not in {"python", "python3"}:
        return {"ok": False, "error": "v4.116.0 code sessions support python/python3 only"}
    exe = _resolve_python(lang)
    if not exe:
        return {"ok": False, "error": f"cannot resolve Python runtime: {lang}"}
    sid = "sess_" + uuid.uuid4().hex[:16]
    workdir = Path(cwd).expanduser() if cwd else (_sessions_root() / sid)
    workdir.mkdir(parents=True, exist_ok=True)
    proc = subprocess.Popen(
        [exe, "-u", "-c", _WORKER],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        cwd=str(workdir),
        env=_scrub_env(),
        bufsize=1,
    )
    sess = Session(id=sid, name=name or sid, lang=lang, proc=proc, cwd=workdir, posture=active)
    threading.Thread(target=_reader, args=(sess,), daemon=True, name=f"arena-code-session-{sid}").start()
    with _SESSIONS_LOCK:
        _SESSIONS[sid] = sess
    return {"ok": True, "session_id": sid, "name": sess.name, "lang": lang, "cwd": str(workdir), "posture": active}


def exec_code(session_id: str, code: str, *, timeout: float = 30) -> dict[str, Any]:
    _cleanup_dead()
    sess = _SESSIONS.get(str(session_id))
    if not sess:
        return {"ok": False, "error": "session not found"}
    if not sess.alive():
        return {"ok": False, "error": "session is not alive"}
    with sess._lock:
        assert sess.proc.stdin is not None
        sess.proc.stdin.write(json.dumps({"code": code}) + "\n")
        sess.proc.stdin.flush()
        try:
            line = sess._q.get(timeout=max(0.1, float(timeout)))
        except queue.Empty:
            stop(session_id)
            return {"ok": False, "timed_out": True, "error": f"session exec timed out after {timeout}s; session stopped"}
        if line is None:
            return {"ok": False, "error": "session terminated"}
        sess.last_used_at = time.time()
        try:
            payload = json.loads(line)
        except Exception as e:
            return {"ok": False, "error": f"bad worker response: {e}", "raw": line[:1000]}
        payload["session_id"] = session_id
        payload["alive"] = sess.alive()
        return payload


def list_sessions() -> dict[str, Any]:
    _cleanup_dead()
    now = time.time()
    with _SESSIONS_LOCK:
        rows = [{
            "session_id": s.id,
            "name": s.name,
            "lang": s.lang,
            "alive": s.alive(),
            "cwd": str(s.cwd),
            "age_sec": round(now - s.started_at, 3),
            "idle_sec": round(now - s.last_used_at, 3),
            "posture": s.posture,
        } for s in _SESSIONS.values()]
    return {"ok": True, "count": len(rows), "sessions": rows}


def stop(session_id: str) -> dict[str, Any]:
    with _SESSIONS_LOCK:
        sess = _SESSIONS.pop(str(session_id), None)
    if not sess:
        return {"ok": False, "error": "session not found"}
    if sess.alive():
        try:
            sess.proc.terminate()
            sess.proc.wait(timeout=5)
        except Exception:
            try:
                sess.proc.kill()
            except Exception:
                pass
    return {"ok": True, "stopped": session_id}


def stop_all() -> dict[str, Any]:
    with _SESSIONS_LOCK:
        ids = list(_SESSIONS)
    out = [stop(sid) for sid in ids]
    return {"ok": True, "stopped": len(out), "results": out}
