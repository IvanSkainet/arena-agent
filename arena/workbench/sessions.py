"""Long-running Code Workbench sessions (v4.116.0 MVP)."""
from __future__ import annotations

import base64
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
    project: str | None = None
    use_project_deps: bool = False
    _q: queue.Queue[str | None] = field(default_factory=queue.Queue)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def alive(self) -> bool:
        return self.proc.poll() is None


_SESSIONS: dict[str, Session] = {}
_SESSIONS_LOCK = threading.Lock()
DEFAULT_MAX_SESSIONS = 8


def _sessions_root() -> Path:
    p = home() / "code-sessions"
    p.mkdir(parents=True, exist_ok=True)
    return p




def _safe_rel(path: str) -> Path:
    rel = Path(str(path).replace("\\", "/"))
    if not str(path).strip() or rel.is_absolute() or rel.drive or any(part in ("..", "") for part in rel.parts):
        raise ValueError(f"unsafe session path: {path!r}")
    return rel


def _get_session(session_id: str) -> tuple[Session | None, dict[str, Any] | None]:
    _cleanup_dead()
    sess = _SESSIONS.get(str(session_id))
    if not sess:
        return None, {"ok": False, "error": "session not found"}
    if not sess.alive():
        return None, {"ok": False, "error": "session is not alive"}
    return sess, None


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


def _cleanup_dead() -> list[dict[str, Any]]:
    removed = []
    with _SESSIONS_LOCK:
        for sid, sess in list(_SESSIONS.items()):
            if not sess.alive():
                removed.append({"session_id": sid, "returncode": sess.proc.poll(), "reason": "dead"})
                _SESSIONS.pop(sid, None)
    return removed


def _max_sessions() -> int:
    try:
        import os
        return max(1, int(os.environ.get("ARENA_CODE_SESSION_MAX", str(DEFAULT_MAX_SESSIONS))))
    except Exception:
        return DEFAULT_MAX_SESSIONS


def _session_row(s: Session, now: float | None = None) -> dict[str, Any]:
    now = now or time.time()
    return {
        "session_id": s.id,
        "name": s.name,
        "lang": s.lang,
        "alive": s.alive(),
        "pid": getattr(s.proc, "pid", None),
        "returncode": s.proc.poll(),
        "cwd": str(s.cwd),
        "age_sec": round(now - s.started_at, 3),
        "idle_sec": round(now - s.last_used_at, 3),
        "posture": s.posture,
        "project": s.project,
        "use_project_deps": s.use_project_deps,
    }


def start(*, lang: str = "python3", name: str = "", cwd: str | None = None,
          project: str | None = None, use_project_deps: bool = False) -> dict[str, Any]:
    _cleanup_dead()
    with _SESSIONS_LOCK:
        live_count = sum(1 for s in _SESSIONS.values() if s.alive())
    limit = _max_sessions()
    if live_count >= limit:
        return {"ok": False, "error": f"code session limit reached ({live_count}/{limit}); stop or sweep sessions first", "count": live_count, "max_sessions": limit}
    active = _posture.load_posture()
    if active.get("sandbox") != "off":
        return {"ok": False, "error": "code_session.start currently requires operator posture sandbox=off (MVP host session). Start a new session after selecting an explicit host/off posture."}
    if lang not in {"python", "python3"}:
        return {"ok": False, "error": "v4.116.0 code sessions support python/python3 only"}
    exe = _resolve_python(lang)
    if not exe:
        return {"ok": False, "error": f"cannot resolve Python runtime: {lang}"}
    sid = "sess_" + uuid.uuid4().hex[:16]
    env = _scrub_env()
    if project:
        from arena.workbench import projects as _projects
        workdir = _projects._project_dir(project)  # project name/path validation lives there
        if not workdir.exists():
            return {"ok": False, "error": "project not found"}
        if use_project_deps:
            env.update(_projects._project_dep_env(project, lang))
    else:
        workdir = Path(cwd).expanduser() if cwd else (_sessions_root() / sid)
    workdir.mkdir(parents=True, exist_ok=True)
    proc = subprocess.Popen(
        [exe, "-u", "-c", _WORKER],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        cwd=str(workdir),
        env=env,
        bufsize=1,
    )
    sess = Session(id=sid, name=name or sid, lang=lang, proc=proc, cwd=workdir, posture=active,
                   project=project, use_project_deps=use_project_deps)
    threading.Thread(target=_reader, args=(sess,), daemon=True, name=f"arena-code-session-{sid}").start()
    with _SESSIONS_LOCK:
        _SESSIONS[sid] = sess
    return {"ok": True, "session_id": sid, "name": sess.name, "lang": lang, "cwd": str(workdir),
            "project": project, "use_project_deps": use_project_deps, "posture": active}


def exec_code(session_id: str, code: str, *, timeout: float = 30, artifacts: list[str] | None = None) -> dict[str, Any]:
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
        if artifacts:
            art = session_artifacts(session_id, artifacts)
            payload["run_id"] = art.get("run_id")
            payload["artifacts"] = art.get("artifacts", [])
            payload["artifact_error"] = art.get("error") if not art.get("ok") else None
        return payload




def write_file(session_id: str, path: str, content: str, *, encoding: str = "utf-8") -> dict[str, Any]:
    sess, err = _get_session(session_id)
    if err:
        return err
    assert sess is not None
    try:
        rel = _safe_rel(path)
        target = sess.cwd / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        if encoding == "base64":
            target.write_bytes(base64.b64decode(str(content)))
        else:
            target.write_text(str(content), encoding="utf-8")
        sess.last_used_at = time.time()
        return {"ok": True, "session_id": session_id, "path": rel.as_posix(), "bytes": target.stat().st_size}
    except Exception as e:
        return {"ok": False, "session_id": session_id, "error": str(e)}


def read_file(session_id: str, path: str, *, max_bytes: int = 100_000) -> dict[str, Any]:
    sess, err = _get_session(session_id)
    if err:
        return err
    assert sess is not None
    try:
        rel = _safe_rel(path)
        target = sess.cwd / rel
        if not target.is_file():
            return {"ok": False, "session_id": session_id, "error": "file not found"}
        data = target.read_bytes()[:max_bytes]
        out: dict[str, Any] = {"ok": True, "session_id": session_id, "path": rel.as_posix(), "bytes": target.stat().st_size, "truncated": target.stat().st_size > max_bytes}
        try:
            out["text"] = data.decode("utf-8")
        except UnicodeDecodeError:
            out["base64"] = base64.b64encode(data).decode("ascii")
        sess.last_used_at = time.time()
        return out
    except Exception as e:
        return {"ok": False, "session_id": session_id, "error": str(e)}


def list_files(session_id: str, *, max_files: int = 200) -> dict[str, Any]:
    sess, err = _get_session(session_id)
    if err:
        return err
    assert sess is not None
    rows = []
    for p in sorted(sess.cwd.rglob("*")):
        if len(rows) >= max_files:
            break
        if p.is_file():
            rows.append({"path": p.relative_to(sess.cwd).as_posix(), "bytes": p.stat().st_size})
    return {"ok": True, "session_id": session_id, "cwd": str(sess.cwd), "count": len(rows), "files": rows, "truncated": len(rows) >= max_files}


def session_artifacts(session_id: str, patterns: list[str] | None = None) -> dict[str, Any]:
    sess, err = _get_session(session_id)
    if err:
        return err
    assert sess is not None
    try:
        from arena.autonomy.runner import _artifact_manifest
        from arena.workbench.artifacts import persist_run
        run_id = uuid.uuid4().hex
        manifest = _artifact_manifest(sess.cwd, [str(p) for p in (patterns or [])])
        persisted = persist_run(run_id, sess.cwd, manifest)
        sess.last_used_at = time.time()
        return {"ok": True, "session_id": session_id, "run_id": run_id, "artifact_count": len(persisted), "artifacts": persisted}
    except Exception as e:
        return {"ok": False, "session_id": session_id, "error": str(e)}


def list_sessions() -> dict[str, Any]:
    _cleanup_dead()
    now = time.time()
    with _SESSIONS_LOCK:
        rows = [_session_row(s, now) for s in _SESSIONS.values()]
    return {"ok": True, "count": len(rows), "max_sessions": _max_sessions(), "sessions": rows}


def stop(session_id: str, *, kill_after: float = 5.0) -> dict[str, Any]:
    with _SESSIONS_LOCK:
        sess = _SESSIONS.pop(str(session_id), None)
    if not sess:
        return {"ok": False, "error": "session not found"}
    killed = False
    terminated = False
    if sess.alive():
        try:
            sess.proc.terminate()
            terminated = True
            sess.proc.wait(timeout=max(0.1, float(kill_after)))
        except Exception:
            try:
                sess.proc.kill()
                killed = True
                sess.proc.wait(timeout=2)
            except Exception:
                pass
    stderr_tail = ""
    try:
        if sess.proc.stderr is not None:
            stderr_tail = (sess.proc.stderr.read() or "")[-2000:]
    except Exception:
        stderr_tail = ""
    return {"ok": True, "stopped": session_id, "terminated": terminated, "killed": killed,
            "returncode": sess.proc.poll(), "stderr_tail": stderr_tail}


def sweep(*, max_idle_sec: float | None = None, max_age_sec: float | None = None,
          dry_run: bool = False) -> dict[str, Any]:
    """Stop stale sessions by idle or age threshold.

    Thresholds are optional; if omitted, no live session is selected. Dead
    sessions are always removed from the in-memory table first.
    """
    removed_dead = _cleanup_dead()
    now = time.time()
    selected = []
    with _SESSIONS_LOCK:
        for s in list(_SESSIONS.values()):
            reasons = []
            if max_idle_sec is not None and now - s.last_used_at >= float(max_idle_sec):
                reasons.append("idle")
            if max_age_sec is not None and now - s.started_at >= float(max_age_sec):
                reasons.append("age")
            if reasons:
                row = _session_row(s, now)
                row["reasons"] = reasons
                selected.append(row)
    stopped = []
    if not dry_run:
        for row in selected:
            stopped.append(stop(row["session_id"]))
    return {"ok": True, "dry_run": dry_run, "dead_removed": removed_dead,
            "selected_count": len(selected), "selected": selected,
            "stopped": stopped, "stopped_count": len(stopped)}


def stop_all() -> dict[str, Any]:
    with _SESSIONS_LOCK:
        ids = list(_SESSIONS)
    out = [stop(sid) for sid in ids]
    return {"ok": True, "stopped": len(out), "results": out}
