"""Third-party skill install/uninstall helpers."""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
import urllib.request
import zipfile
from pathlib import Path
from typing import Any


def install_skill(name: str, url: str, *, skills_dir: Path) -> dict[str, Any]:
    if not name or not url:
        return {"ok": False, "error": "name and url are required"}
    if ".." in name or "/" in name or "\\" in name:
        return {"ok": False, "error": "invalid skill name"}

    target_dir = skills_dir / "third_party" / name
    if target_dir.exists():
        return {"ok": False, "error": "skill already installed"}
    target_dir.parent.mkdir(parents=True, exist_ok=True)

    try:
        if url.endswith(".zip"):
            # On Windows, NamedTemporaryFile keeps an exclusive handle while the
            # context is open, so copying/downloading into tmp.name can fail with
            # WinError 32. Allocate the name, close the handle, then populate it.
            tmp_path = ""
            try:
                with tempfile.NamedTemporaryFile(delete=False, suffix=".zip") as tmp:
                    tmp_path = tmp.name
                if os.path.exists(url):
                    shutil.copy(url, tmp_path)
                elif url.startswith("file://"):
                    local_p = url[7:]
                    if os.path.exists(local_p):
                        shutil.copy(local_p, tmp_path)
                    else:
                        return {"ok": False, "error": f"zip file not found: {local_p}"}
                else:
                    urllib.request.urlretrieve(url, tmp_path)
                with zipfile.ZipFile(tmp_path, "r") as zip_ref:
                    non_junk_names = [
                        p for p in zip_ref.namelist()
                        if p and not any(part.startswith(".") or part in ("__MACOSX", "desktop.ini", "Thumbs.db") for part in p.split("/"))
                    ]
                    root_names = set(p.split("/")[0] for p in non_junk_names if p)
                    if len(root_names) == 1:
                        root = list(root_names)[0]
                        temp_ext = target_dir.parent / (name + "_temp")
                        zip_ref.extractall(temp_ext)
                        if (temp_ext / root).exists():
                            os.rename(temp_ext / root, target_dir)
                        else:
                            zip_ref.extractall(target_dir)
                        shutil.rmtree(temp_ext, ignore_errors=True)
                    else:
                        zip_ref.extractall(target_dir)
            finally:
                if tmp_path:
                    try:
                        os.unlink(tmp_path)
                    except OSError:
                        pass
        else:
            subprocess.run(["git", "clone", "--depth", "1", "--", url, str(target_dir)], check=True, capture_output=True)
            shutil.rmtree(target_dir / ".git", ignore_errors=True)
        return {"ok": True, "path": str(target_dir), "name": name}
    except Exception as e:
        shutil.rmtree(target_dir, ignore_errors=True)
        return {"ok": False, "error": str(e)}


def normalize_third_party_skill_name(name: str) -> tuple[str | None, str | None]:
    """Return safe third-party skill basename or an error string."""
    raw = (name or "").strip().strip("/")
    if not raw:
        return None, "missing skill name"
    if raw.startswith("skills/third_party/"):
        raw = raw[len("skills/third_party/"):]
    elif raw.startswith("third_party/"):
        raw = raw[len("third_party/"):]
    elif "/" in raw or "\\" in raw:
        return None, "only third-party skills can be uninstalled by this endpoint"
    if not re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9._-]{0,127}", raw):
        return None, "invalid skill name"
    if raw in (".", ".."):
        return None, "invalid skill name"
    return raw, None


def uninstall_skill(name: str, *, skills_dir: Path) -> dict[str, Any]:
    safe_name, err = normalize_third_party_skill_name(name)
    if err:
        return {"ok": False, "error": err}

    target_dir = (skills_dir / "third_party" / safe_name).resolve()
    allowed_root = (skills_dir / "third_party").resolve()
    try:
        target_dir.relative_to(allowed_root)
    except ValueError:
        return {"ok": False, "error": "invalid skill path"}
    if not target_dir.exists():
        return {"ok": False, "error": f"third-party skill '{safe_name}' not found"}
    if not target_dir.is_dir():
        return {"ok": False, "error": f"third-party skill '{safe_name}' is not a directory"}

    try:
        shutil.rmtree(target_dir)
        return {"ok": True, "removed": safe_name, "name": f"third_party/{safe_name}", "path": str(target_dir)}
    except Exception as e:
        return {"ok": False, "error": str(e)}
