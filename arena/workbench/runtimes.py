"""Managed runtime registry/probe/install for the Code Workbench."""
from __future__ import annotations

import hashlib
import json
import os
import platform
import shutil
import subprocess
import tarfile
import urllib.request
import zipfile
from pathlib import Path
from typing import Any

_GO_INDEX = "https://go.dev/dl/?mode=json"


def home() -> Path:
    return Path(os.environ.get("ARENA_AGENT_HOME") or (Path.home() / "arena-bridge")).expanduser()


def tools_dir() -> Path:
    p = home() / "tools"
    p.mkdir(parents=True, exist_ok=True)
    return p


def registry_path() -> Path:
    p = home() / "runtime" / "runtimes.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def load_registry() -> dict[str, Any]:
    p = registry_path()
    if not p.exists():
        return {"runtimes": {}}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {"runtimes": {}}
    except Exception:
        return {"runtimes": {}}


def save_registry(data: dict[str, Any]) -> None:
    registry_path().write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def _run_version(exe: str, args: list[str] | None = None) -> str | None:
    try:
        proc = subprocess.run([exe, *(args or ["--version"])], capture_output=True, text=True, timeout=10)
    except Exception:
        return None
    out = (proc.stdout or proc.stderr or "").strip()
    return out.splitlines()[0] if out else None


def _which(name: str) -> str | None:
    return shutil.which(name)


def _managed_go_path(version: str | None = None) -> Path | None:
    root = tools_dir()
    if version:
        p = root / f"go{version}" / "bin" / ("go.exe" if platform.system().lower() == "windows" else "go")
        return p if p.exists() else None
    for d in sorted(root.glob("go*"), reverse=True):
        p = d / "bin" / ("go.exe" if platform.system().lower() == "windows" else "go")
        if p.exists():
            return p
    return None


def probe() -> dict[str, Any]:
    reg = load_registry().get("runtimes", {})
    out: dict[str, Any] = {"ok": True, "managed_home": str(tools_dir()), "runtimes": {}}
    checks = {
        "python": ["python", "--version"],
        "python3": ["python3", "--version"],
        "node": ["node", "--version"],
        "go": ["go", "version"],
        "rustc": ["rustc", "--version"],
        "cargo": ["cargo", "--version"],
        "java": ["java", "--version"],
    }
    for name, cmd in checks.items():
        exe = _which(cmd[0])
        out["runtimes"][name] = {"available": bool(exe), "path": exe, "version": _run_version(exe, cmd[1:]) if exe else None, "managed": False}
    go_managed = _managed_go_path()
    if go_managed:
        out["runtimes"]["go"] = {"available": True, "path": str(go_managed), "version": _run_version(str(go_managed), ["version"]), "managed": True}
    for name, meta in reg.items():
        out["runtimes"].setdefault(name, {}).update({"registry": meta})
    # Rust diagnosis: compiler alone is not enough on Windows.
    rust = out["runtimes"].get("rustc", {})
    if rust.get("available") and platform.system().lower() == "windows":
        rust["linker_available"] = bool(_which("link.exe") or _which("gcc") or _which("clang"))
        if not rust["linker_available"]:
            rust["diagnosis"] = "rustc is installed, but no MSVC/MinGW/clang linker is on PATH"
    return out


def _download(url: str, dest: Path) -> None:
    req = urllib.request.Request(url, headers={"User-Agent": "ArenaBridge/runtime.install"})
    with urllib.request.urlopen(req, timeout=120) as r:  # nosec B310 -- fixed public runtime URLs selected from upstream release metadata
        with dest.open("wb") as f:
            shutil.copyfileobj(r, f)


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _safe_join_extract(base: Path, member_name: str) -> Path:
    target = (base / member_name).resolve()
    base_resolved = base.resolve()
    if target != base_resolved and base_resolved not in target.parents:
        raise RuntimeError(f"archive member escapes destination: {member_name}")
    return target


def _extract_zip_safe(archive: Path, dest: Path) -> None:
    with zipfile.ZipFile(archive) as z:
        for info in z.infolist():
            target = _safe_join_extract(dest, info.filename)
            if info.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with z.open(info) as src, target.open("wb") as out:
                shutil.copyfileobj(src, out)


def _extract_tar_safe(archive: Path, dest: Path) -> None:
    with tarfile.open(archive) as t:
        for member in t.getmembers():
            target = _safe_join_extract(dest, member.name)
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            if not member.isfile():
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            src = t.extractfile(member)
            if src is None:
                continue
            with src, target.open("wb") as out:
                shutil.copyfileobj(src, out)


def _go_asset(version: str | None = None) -> dict[str, Any]:
    req = urllib.request.Request(_GO_INDEX, headers={"User-Agent": "ArenaBridge/runtime.install"})
    with urllib.request.urlopen(req, timeout=60) as r:  # nosec B310 -- fixed official Go release index
        releases = json.loads(r.read().decode("utf-8"))
    want_ver = version if version and version.startswith("go") else (f"go{version}" if version else None)
    sysname = platform.system().lower()
    os_name = {"windows": "windows", "linux": "linux", "darwin": "darwin"}.get(sysname)
    arch = "amd64" if platform.machine().lower() in {"amd64", "x86_64"} else platform.machine().lower()
    kind = "archive"
    for rel in releases:
        if want_ver and rel.get("version") != want_ver:
            continue
        for f in rel.get("files", []):
            if f.get("os") == os_name and f.get("arch") == arch and f.get("kind") == kind:
                return {**f, "release": rel.get("version")}
    raise RuntimeError(f"no Go archive found for version={version!r} os={os_name} arch={arch}")


def install_go(version: str | None = None) -> dict[str, Any]:
    asset = _go_asset(version)
    ver = asset["version"]  # e.g. go1.26.5
    root = tools_dir()
    target = root / ver
    exe = target / "bin" / ("go.exe" if platform.system().lower() == "windows" else "go")
    if exe.exists():
        return {"ok": True, "runtime": "go", "version": ver, "path": str(exe), "already_installed": True, "probe": _run_version(str(exe), ["version"])}
    url = f"https://go.dev/dl/{asset['filename']}"
    archive = root / asset["filename"]
    if not archive.exists():
        _download(url, archive)
    got = _sha256(archive)
    if got.lower() != str(asset["sha256"]).lower():
        raise RuntimeError(f"sha256 mismatch for {archive.name}: got {got}, expected {asset['sha256']}")
    tmp = root / f".{ver}.extract"
    if tmp.exists():
        shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir(parents=True)
    if archive.suffix.lower() == ".zip":
        _extract_zip_safe(archive, tmp)
    else:
        _extract_tar_safe(archive, tmp)
    extracted = tmp / "go"
    if not extracted.exists():
        raise RuntimeError("Go archive did not contain top-level go directory")
    if target.exists():
        shutil.rmtree(target, ignore_errors=True)
    extracted.rename(target)
    shutil.rmtree(tmp, ignore_errors=True)
    reg = load_registry()
    reg.setdefault("runtimes", {})["go"] = {"version": ver, "path": str(exe), "managed": True, "source": url, "sha256": got}
    save_registry(reg)
    return {"ok": True, "runtime": "go", "version": ver, "path": str(exe), "sha256": got, "probe": _run_version(str(exe), ["version"])}


def install(runtime: str, version: str | None = None) -> dict[str, Any]:
    if runtime == "go":
        return install_go(version)
    return {"ok": False, "error": f"runtime.install currently supports: go (got {runtime!r})"}
