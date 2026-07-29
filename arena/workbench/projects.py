"""Persistent Code Workbench project store."""
from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

from arena.autonomy import posture as _posture
from arena.autonomy import runner as _runner
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


def deps_install(name: str, *, lang: str, deps: dict[str, Any], timeout: int | None = None) -> dict[str, Any]:
    d = _project_dir(name)
    if not d.exists():
        return {"ok": False, "error": "project not found"}
    posture = _posture.load_posture()
    if posture.get("network") != "open":
        return {"ok": False, "error": "code_project.deps_install requires operator posture network=open"}
    from arena.autonomy import deps as _deps
    return _deps.install_deps(
        d, "win32" if __import__("sys").platform == "win32" else __import__("sys").platform,
        lang, deps, posture, timeout or 120,
        resolve_runtime=_runner._resolve_runtime,
        resolve_win32_runtime=_runner._resolve_win32_runtime,
        managed_go_root=_runner._managed_go_root,
        scrub_env=_runner._scrub_env,
        trim=_runner._trim,
    )


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
        timeout: int | None = None, platform: str | None = None) -> dict[str, Any]:
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
    return _runner.run_code_sync("", lang, posture, timeout=timeout, platform=platform,
                                 env=env, files=files, entry=entry, argv=argv or [], stdin=stdin,
                                 artifacts=artifacts or [], deps=deps,
                                 extra_grant_dirs=extra_grant_dirs)
