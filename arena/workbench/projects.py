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


def run(name: str, *, lang: str, entry: str, argv: list[str] | None = None,
        stdin: str | None = None, artifacts: list[str] | None = None,
        deps: dict[str, Any] | None = None,
        timeout: int | None = None, platform: str | None = None) -> dict[str, Any]:
    d = _project_dir(name)
    if not d.exists():
        return {"ok": False, "error": "project not found"}
    files = []
    for p in d.rglob("*"):
        if p.is_file() and p.name != ".arena-project.json":
            rel = p.relative_to(d).as_posix()
            try:
                files.append({"path": rel, "content": p.read_text(encoding="utf-8")})
            except UnicodeDecodeError:
                import base64
                files.append({"path": rel, "content": base64.b64encode(p.read_bytes()).decode("ascii"), "encoding": "base64"})
    return _runner.run_code_sync("", lang, _posture.load_posture(), timeout=timeout, platform=platform,
                                 files=files, entry=entry, argv=argv or [], stdin=stdin, artifacts=artifacts or [], deps=deps)
