"""Persistent Code Workbench project store."""
from __future__ import annotations

import hashlib
import json
import shutil
import sys
import time
from pathlib import Path
from typing import Any

from arena.autonomy import posture as _posture, runner as _runner
from arena.workbench.runtimes import home


def root() -> Path:
    p = home() / "code-projects"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _safe_name(name: str) -> str:
    n = str(name or "").strip()
    if not n or any(c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-" for c in n) or n in {".", ".."}:
        raise ValueError("project name must use only letters, digits, dot, underscore and dash")
    return n[:80]


def _project_dir(name: str) -> Path:
    return root() / _safe_name(name)


def _safe_rel(path: str) -> Path:
    rel = Path(str(path).replace("\\", "/"))
    if not str(path).strip() or rel.is_absolute() or rel.drive or any(part in ("..", "") for part in rel.parts):
        raise ValueError(f"unsafe project path: {path!r}")
    return rel


def create(name: str, files: list[dict[str, Any]] | None = None, *, overwrite: bool = False) -> dict[str, Any]:
    d = _project_dir(name)
    if d.exists() and not overwrite:
        return {"ok": False, "error": "project already exists", "project": _safe_name(name)}
    d.mkdir(parents=True, exist_ok=True)
    written = []
    for item in files or []:
        r = write(name, item.get("path", ""), item.get("content", ""), encoding=item.get("encoding", "utf-8"))
        if not r.get("ok"):
            return r
        written.append(r["path"])
    meta = {"name": _safe_name(name), "files": written}
    (d / ".arena-project.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    return {"ok": True, "project": meta["name"], "path": str(d), "files": written}


def list_projects() -> dict[str, Any]:
    projects = []
    for d in sorted(root().iterdir()):
        if d.is_dir():
            files = [p.relative_to(d).as_posix() for p in d.rglob("*") if p.is_file() and p.name != ".arena-project.json"]
            projects.append({"name": d.name, "path": str(d), "file_count": len(files), "files": files[:50]})
    return {"ok": True, "count": len(projects), "projects": projects}


def write(name: str, path: str, content: str, *, encoding: str = "utf-8") -> dict[str, Any]:
    d = _project_dir(name)
    d.mkdir(parents=True, exist_ok=True)
    rel = _safe_rel(path)
    target = d / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    if encoding == "base64":
        import base64
        target.write_bytes(base64.b64decode(str(content)))
    else:
        target.write_text(str(content), encoding="utf-8")
    return {"ok": True, "project": _safe_name(name), "path": rel.as_posix(), "bytes": target.stat().st_size}


def read(name: str, path: str, *, max_bytes: int = 100_000) -> dict[str, Any]:
    d = _project_dir(name)
    target = d / _safe_rel(path)
    if not target.exists() or not target.is_file():
        return {"ok": False, "error": "file not found"}
    data = target.read_bytes()[:max_bytes]
    try:
        return {"ok": True, "project": _safe_name(name), "path": _safe_rel(path).as_posix(), "text": data.decode("utf-8"), "bytes": target.stat().st_size}
    except UnicodeDecodeError:
        import base64
        return {"ok": True, "project": _safe_name(name), "path": _safe_rel(path).as_posix(), "base64": base64.b64encode(data).decode("ascii"), "bytes": target.stat().st_size}


def remove(name: str) -> dict[str, Any]:
    d = _project_dir(name)
    if not d.exists():
        return {"ok": False, "error": "project not found"}
    shutil.rmtree(d)
    return {"ok": True, "removed": _safe_name(name)}



def _lock_path(name: str) -> Path:
    return _project_dir(name) / ".arena-lock.json"


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _freeze_python(path: Path) -> list[str]:
    rows = []
    if not path.exists():
        return rows
    for dist in sorted(path.glob("*.dist-info/METADATA")):
        name = ""
        version = ""
        try:
            for line in dist.read_text(encoding="utf-8", errors="replace").splitlines():
                if line.startswith("Name:"):
                    name = line.split(":", 1)[1].strip()
                elif line.startswith("Version:"):
                    version = line.split(":", 1)[1].strip()
                if name and version:
                    break
        except Exception:
            continue
        if name and version:
            rows.append(f"{name}=={version}")
    return rows


def _capture_lock(name: str, *, lang: str, requested: dict[str, Any] | None = None,
                  install_result: dict[str, Any] | None = None) -> dict[str, Any]:
    d = _project_dir(name)
    py = _freeze_python(d / ".deps" / "python") if lang in {"python", "python3"} else []
    npm_lock = d / ".deps" / "node" / "package-lock.json"
    go_sum = d / "go.sum"
    runtime_probe = None
    try:
        runtime_probe = _runner._resolve_win32_runtime(lang) if sys.platform == "win32" and lang in {"python", "python3"} else _runner._resolve_runtime(lang)
    except Exception:
        runtime_probe = None
    doc: dict[str, Any] = {
        "ok": True,
        "schema": "arena.project.lock.v1",
        "project": _safe_name(name),
        "lang": lang,
        "created_at": int(time.time()),
        "platform": sys.platform,
        "runtime": {"path": runtime_probe},
        "requested": requested or {},
        "resolved": {
            "python": py,
            "npm_package_lock_sha256": hashlib.sha256(npm_lock.read_bytes()).hexdigest() if npm_lock.exists() else None,
            "go_sum_sha256": hashlib.sha256(go_sum.read_bytes()).hexdigest() if go_sum.exists() else None,
        },
        "install_result_summary": install_result or {},
    }
    canonical = json.dumps({k: v for k, v in doc.items() if k != "sha256"}, sort_keys=True, ensure_ascii=False)
    doc["sha256"] = _sha256_text(canonical)
    return doc


def lock(name: str, *, lang: str = "python3", deps: dict[str, Any] | None = None) -> dict[str, Any]:
    d = _project_dir(name)
    if not d.exists():
        return {"ok": False, "error": "project not found"}
    doc = _capture_lock(name, lang=lang, requested=deps or {})
    _lock_path(name).write_text(json.dumps(doc, indent=2, ensure_ascii=False), encoding="utf-8")
    return {"ok": True, "project": _safe_name(name), "path": ".arena-lock.json", "lock": doc}


def lock_read(name: str) -> dict[str, Any]:
    p = _lock_path(name)
    if not p.exists():
        return {"ok": False, "error": "lock not found"}
    try:
        doc = json.loads(p.read_text(encoding="utf-8"))
    except Exception as e:
        return {"ok": False, "error": f"invalid lock: {e}"}
    return {"ok": True, "project": _safe_name(name), "path": ".arena-lock.json", "lock": doc}


def lock_verify(name: str, *, lang: str | None = None, mode: str = "strict") -> dict[str, Any]:
    got = lock_read(name)
    if not got.get("ok"):
        return {"ok": False, "match": False, "error": got.get("error"), "mode": mode}
    saved = got["lock"]
    current = _capture_lock(name, lang=lang or saved.get("lang") or "python3", requested=saved.get("requested") or {})
    mismatches = []
    for key in ("python", "npm_package_lock_sha256", "go_sum_sha256"):
        if (saved.get("resolved") or {}).get(key) != (current.get("resolved") or {}).get(key):
            mismatches.append({"field": f"resolved.{key}", "expected": (saved.get("resolved") or {}).get(key), "actual": (current.get("resolved") or {}).get(key)})
    ok = not mismatches
    return {"ok": ok, "match": ok, "project": _safe_name(name), "mode": mode, "mismatches": mismatches, "lock": saved, "current": current}


def _lock_gate(name: str, lang: str, lock_mode: str | None) -> dict[str, Any] | None:
    mode = (lock_mode or "ignore").lower()
    if mode in {"", "ignore", "none"}:
        return None
    result = lock_verify(name, lang=lang, mode=mode)
    if result.get("match"):
        return {"ok": True, "lock": result}
    if mode == "warn":
        return {"ok": True, "warning": result}
    return {"ok": False, "error": "project dependency lock mismatch" if result.get("lock") else result.get("error", "project dependency lock missing"), "lock": result}


def deps_install(name: str, *, lang: str, deps: dict[str, Any], timeout: int | None = None, write_lock: bool = True) -> dict[str, Any]:
    d = _project_dir(name)
    if not d.exists():
        return {"ok": False, "error": "project not found"}
    posture = _posture.load_posture()
    if posture.get("network") != "open":
        return {"ok": False, "error": "code_project.deps_install requires operator posture network=open"}
    from arena.autonomy import deps as _deps
    res = _deps.install_deps(
        d, "win32" if __import__("sys").platform == "win32" else __import__("sys").platform,
        lang, deps, posture, timeout or 120,
        resolve_runtime=_runner._resolve_runtime,
        resolve_win32_runtime=_runner._resolve_win32_runtime,
        managed_go_root=_runner._managed_go_root,
        scrub_env=_runner._scrub_env,
        trim=_runner._trim,
    )
    if res.get("ok") and write_lock:
        locked = lock(name, lang=lang, deps=deps)
        res["lock"] = locked.get("lock")
        res["lock_path"] = locked.get("path")
    return res


def _project_dep_dirs(name: str, lang: str) -> list[Path]:
    d = _project_dir(name)
    dirs: list[Path] = []
    py = d / ".deps" / "python"
    if py.exists() and lang in {"python", "python3"}:
        dirs.append(py)
    node = d / ".deps" / "node" / "node_modules"
    if node.exists() and lang == "node":
        dirs.append(node)
    if lang == "go":
        for p in (d / ".deps" / "go-mod", d / ".deps" / "go-cache", d / ".deps" / "go-tmp"):
            if p.exists():
                dirs.append(p)
    return dirs


def _project_dep_env(name: str, lang: str) -> dict[str, str]:
    d = _project_dir(name)
    env: dict[str, str] = {}
    py = d / ".deps" / "python"
    if py.exists() and lang in {"python", "python3"}:
        env["PYTHONPATH"] = str(py)
    node = d / ".deps" / "node" / "node_modules"
    if node.exists() and lang == "node":
        env["NODE_PATH"] = str(node)
    if lang == "go":
        go_mod = d / ".deps" / "go-mod"
        go_cache = d / ".deps" / "go-cache"
        go_tmp = d / ".deps" / "go-tmp"
        for p in (go_mod, go_cache, go_tmp):
            p.mkdir(parents=True, exist_ok=True)
        env.update({"GOMODCACHE": str(go_mod), "GOCACHE": str(go_cache), "GOTMPDIR": str(go_tmp)})
    return env


def run(name: str, *, lang: str, entry: str, argv: list[str] | None = None,
        stdin: str | None = None, artifacts: list[str] | None = None,
        deps: dict[str, Any] | None = None, use_project_deps: bool = False,
        timeout: int | None = None, platform: str | None = None,
        lock_mode: str | None = None) -> dict[str, Any]:
    d = _project_dir(name)
    if not d.exists():
        return {"ok": False, "error": "project not found"}
    files = []
    for p in d.rglob("*"):
        rel_parts = p.relative_to(d).parts
        if rel_parts and rel_parts[0] in {".deps", ".arena-deps", "node_modules", "__pycache__"}:
            continue
        if p.is_file() and p.name != ".arena-project.json":
            rel = p.relative_to(d).as_posix()
            try:
                files.append({"path": rel, "content": p.read_text(encoding="utf-8")})
            except UnicodeDecodeError:
                import base64
                files.append({"path": rel, "content": base64.b64encode(p.read_bytes()).decode("ascii"), "encoding": "base64"})
    posture = _posture.load_posture()
    env = None
    extra_grant_dirs = None
    if use_project_deps:
        sandbox = posture.get("sandbox")
        if sandbox not in {"off", "appcontainer"}:
            return {"ok": False, "error": "use_project_deps currently supports sandbox=off or Windows AppContainer project-deps grants"}
        env = {**_runner._scrub_env(), **_project_dep_env(name, lang)}
        if sandbox == "appcontainer":
            extra_grant_dirs = _project_dep_dirs(name, lang)
            if not extra_grant_dirs:
                return {"ok": False, "error": "use_project_deps requested but no project dependency cache exists for this language"}
    lock_check = _lock_gate(name, lang, lock_mode)
    if lock_check and not lock_check.get("ok"):
        return {"ok": False, **lock_check}
    result = _runner.run_code_sync("", lang, posture, timeout=timeout, platform=platform,
                                   env=env, files=files, entry=entry, argv=argv or [], stdin=stdin,
                                   artifacts=artifacts or [], deps=deps,
                                   extra_grant_dirs=extra_grant_dirs)
    if lock_check:
        result["lock"] = lock_check.get("lock") or lock_check.get("warning")
    return result
