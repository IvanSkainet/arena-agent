"""Scratch-local dependency installation for Code Workbench runs."""
from __future__ import annotations

import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable

_PY_DEP_RE = re.compile(r"^[A-Za-z0-9_.\-\[\]]+([<>=!~]=?[A-Za-z0-9_.\-*+]+)?(,[<>=!~]=?[A-Za-z0-9_.\-*+]+)*$")
_NPM_DEP_RE = re.compile(r"^(@[A-Za-z0-9_.-]+/)?[A-Za-z0-9_.-]+(@[A-Za-z0-9_.\-+]+)?$")

TrimFn = Callable[[Any, int], str]
ResolveFn = Callable[[str], str | None]


def _npm_for_deps(resolve_runtime: ResolveFn) -> str | None:
    found = shutil.which("npm") or shutil.which("npm.cmd")
    if found:
        return found
    node = resolve_runtime("node")
    if node:
        p = Path(node).resolve().parent / ("npm.cmd" if sys.platform == "win32" else "npm")
        if p.exists():
            return str(p)
    return None


def _python_exe_for_deps(platform: str, lang: str, resolve_runtime: ResolveFn,
                         resolve_win32_runtime: ResolveFn) -> str | None:
    return resolve_win32_runtime(lang) if platform == "win32" else resolve_runtime(lang)


def install_python_deps(scratch: Path, platform: str, lang: str, deps: dict[str, Any] | None,
                        posture: dict[str, Any], timeout: int, *, resolve_runtime: ResolveFn,
                        resolve_win32_runtime: ResolveFn, scrub_env: Callable[[], dict[str, str]],
                        trim: TrimFn) -> dict[str, Any]:
    pkgs = (deps or {}).get("python") if isinstance(deps, dict) else None
    if not pkgs:
        return {"ok": True, "installed": [], "path": None}
    if lang not in {"python", "python3"}:
        return {"ok": False, "error": "deps.python is only supported for lang=python/python3"}
    if posture.get("network") != "open":
        return {"ok": False, "error": "deps.python requires operator posture network=open for package download"}
    if not isinstance(pkgs, list) or len(pkgs) > 20:
        return {"ok": False, "error": "deps.python must be an array of at most 20 package specs"}
    specs = [str(p).strip() for p in pkgs]
    bad = [p for p in specs if not p or not _PY_DEP_RE.match(p)]
    if bad:
        return {"ok": False, "error": f"unsupported python dependency spec(s): {bad}"}
    py = _python_exe_for_deps(platform, lang, resolve_runtime, resolve_win32_runtime)
    if not py:
        return {"ok": False, "error": f"cannot resolve Python runtime for dependency install: {lang}"}
    target = scratch / ".deps" / "python"
    target.mkdir(parents=True, exist_ok=True)
    cmd = [py, "-m", "pip", "install", "--disable-pip-version-check", "--no-input",
           "--retries", "1", "--timeout", "30", "--target", str(target), *specs]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=max(timeout, 60), env=scrub_env())
    except subprocess.TimeoutExpired as e:
        return {"ok": False, "error": f"pip install timed out after {max(timeout, 60)}s", "stdout": trim(e.stdout or "", 4000), "stderr": trim(e.stderr or "", 4000)}
    if proc.returncode != 0:
        return {"ok": False, "error": "pip install failed", "exit_code": proc.returncode,
                "stdout": trim(proc.stdout, 4000), "stderr": trim(proc.stderr, 4000)}
    return {"ok": True, "installed": specs, "path": str(target), "stdout": trim(proc.stdout, 4000), "stderr": trim(proc.stderr, 4000)}


def install_node_deps(scratch: Path, lang: str, deps: dict[str, Any] | None,
                      posture: dict[str, Any], timeout: int, *, resolve_runtime: ResolveFn,
                      scrub_env: Callable[[], dict[str, str]], trim: TrimFn) -> dict[str, Any]:
    pkgs = (deps or {}).get("npm") if isinstance(deps, dict) else None
    if not pkgs:
        return {"ok": True, "installed": [], "path": None}
    if lang != "node":
        return {"ok": False, "error": "deps.npm is only supported for lang=node"}
    if posture.get("network") != "open":
        return {"ok": False, "error": "deps.npm requires operator posture network=open for package download"}
    if not isinstance(pkgs, list) or len(pkgs) > 20:
        return {"ok": False, "error": "deps.npm must be an array of at most 20 package specs"}
    specs = [str(p).strip() for p in pkgs]
    bad = [p for p in specs if not p or not _NPM_DEP_RE.match(p)]
    if bad:
        return {"ok": False, "error": f"unsupported npm dependency spec(s): {bad}"}
    npm = _npm_for_deps(resolve_runtime)
    if not npm:
        return {"ok": False, "error": "cannot resolve npm runtime for dependency install"}
    target = scratch / ".deps" / "node"
    target.mkdir(parents=True, exist_ok=True)
    cmd = [npm, "install", "--prefix", str(target), "--no-save", "--no-audit", "--no-fund", *specs]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=max(timeout, 60), env=scrub_env())
    except subprocess.TimeoutExpired as e:
        return {"ok": False, "error": f"npm install timed out after {max(timeout, 60)}s", "stdout": trim(e.stdout or "", 4000), "stderr": trim(e.stderr or "", 4000)}
    if proc.returncode != 0:
        return {"ok": False, "error": "npm install failed", "exit_code": proc.returncode,
                "stdout": trim(proc.stdout, 4000), "stderr": trim(proc.stderr, 4000)}
    return {"ok": True, "installed": specs, "path": str(target / "node_modules"), "stdout": trim(proc.stdout, 4000), "stderr": trim(proc.stderr, 4000)}


def go_env_for_scratch(scratch: Path, managed_go_root: Callable[[], str | None],
                       scrub_env: Callable[[], dict[str, str]]) -> dict[str, str]:
    env = scrub_env()
    go_root = managed_go_root()
    if go_root:
        env["GOROOT"] = go_root
    for key, rel in {"GOCACHE": "go-cache", "GOMODCACHE": "go-mod", "GOTMPDIR": "go-tmp"}.items():
        p = scratch / rel
        p.mkdir(parents=True, exist_ok=True)
        env[key] = str(p)
    return env


def install_go_deps(scratch: Path, lang: str, deps: dict[str, Any] | None,
                    posture: dict[str, Any], timeout: int, *, resolve_runtime: ResolveFn,
                    managed_go_root: Callable[[], str | None], scrub_env: Callable[[], dict[str, str]],
                    trim: TrimFn) -> dict[str, Any]:
    enabled = (deps or {}).get("go") if isinstance(deps, dict) else None
    if not enabled:
        return {"ok": True, "enabled": False}
    if lang != "go":
        return {"ok": False, "error": "deps.go is only supported for lang=go"}
    if posture.get("network") != "open":
        return {"ok": False, "error": "deps.go requires operator posture network=open for module download"}
    if not (scratch / "go.mod").exists():
        return {"ok": False, "error": "deps.go requires go.mod in the workspace"}
    go = resolve_runtime("go")
    if not go:
        return {"ok": False, "error": "cannot resolve Go runtime for module download"}
    try:
        proc = subprocess.run([go, "mod", "download"], cwd=str(scratch), capture_output=True,
                              text=True, timeout=max(timeout, 60), env=go_env_for_scratch(scratch, managed_go_root, scrub_env))
    except subprocess.TimeoutExpired as e:
        return {"ok": False, "error": f"go mod download timed out after {max(timeout, 60)}s",
                "stdout": trim(e.stdout or "", 4000), "stderr": trim(e.stderr or "", 4000)}
    if proc.returncode != 0:
        return {"ok": False, "error": "go mod download failed", "exit_code": proc.returncode,
                "stdout": trim(proc.stdout, 4000), "stderr": trim(proc.stderr, 4000)}
    return {"ok": True, "enabled": True, "stdout": trim(proc.stdout, 4000), "stderr": trim(proc.stderr, 4000)}


def install_deps(scratch: Path, platform: str, lang: str, deps: dict[str, Any] | None,
                 posture: dict[str, Any], timeout: int, *, resolve_runtime: ResolveFn,
                 resolve_win32_runtime: ResolveFn, managed_go_root: Callable[[], str | None],
                 scrub_env: Callable[[], dict[str, str]], trim: TrimFn) -> dict[str, Any]:
    py = install_python_deps(scratch, platform, lang, deps, posture, timeout,
                             resolve_runtime=resolve_runtime, resolve_win32_runtime=resolve_win32_runtime,
                             scrub_env=scrub_env, trim=trim)
    if not py.get("ok"):
        return {"ok": False, "python": py, "error": py.get("error")}
    npm = install_node_deps(scratch, lang, deps, posture, timeout,
                            resolve_runtime=resolve_runtime, scrub_env=scrub_env, trim=trim)
    if not npm.get("ok"):
        return {"ok": False, "python": py, "npm": npm, "error": npm.get("error")}
    go = install_go_deps(scratch, lang, deps, posture, timeout, resolve_runtime=resolve_runtime,
                         managed_go_root=managed_go_root, scrub_env=scrub_env, trim=trim)
    if not go.get("ok"):
        return {"ok": False, "python": py, "npm": npm, "go": go, "error": go.get("error")}
    return {"ok": True, "python": py, "npm": npm, "go": go}
