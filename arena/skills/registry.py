"""Skill registry scanning helpers."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def parse_skill_folder(skills_dir: Path, folder: Path, *, is_third_party: bool = False, category: str = "") -> dict[str, Any]:
    prefix = "third_party/" if is_third_party else (f"{category}/" if category else "")
    name = f"{prefix}{folder.name}"
    skill_info: dict[str, Any] = {
        "name": name,
        "file": str(folder.relative_to(skills_dir)),
        "is_third_party": is_third_party,
        "description": "",
        "version": "",
    }

    manifest = folder / "manifest.json"
    if manifest.exists():
        try:
            data = json.loads(manifest.read_text(encoding="utf-8"))
            skill_info["description"] = data.get("description", "")
            skill_info["version"] = data.get("version", "")
        except Exception:
            pass

    if not skill_info["description"]:
        skill_md = folder / "SKILL.md"
        if skill_md.exists():
            try:
                lines = skill_md.read_text(encoding="utf-8").splitlines()
                desc_lines = [line.strip() for line in lines if line.strip() and not line.startswith("#")][:2]
                if desc_lines:
                    skill_info["description"] = " ".join(desc_lines)[:100]
            except Exception:
                pass
    return skill_info


def scan_skills(skills_dir: Path) -> dict[str, Any]:
    """Scan a skills directory for skill definitions."""
    skills: list[dict[str, Any]] = []
    if not skills_dir.exists():
        return {"ok": True, "count": 0, "skills": []}

    for path in sorted(skills_dir.iterdir()):
        if not path.is_dir() or path.name.startswith("."):
            continue
        if path.name == "third_party":
            for third_party in sorted(path.iterdir()):
                if third_party.is_dir() and not third_party.name.startswith("."):
                    skills.append(parse_skill_folder(skills_dir, third_party, is_third_party=True))
            continue

        # Top-level skill or category?
        direct_skill_files = [
            "manifest.json",
            "SKILL.md",
            "run.sh",
            "run.py",
            f"{path.name}.py",
            f"{path.name}.sh",
        ]
        if any((path / filename).exists() for filename in direct_skill_files):
            skills.append(parse_skill_folder(skills_dir, path, is_third_party=False))
        else:
            for sub in sorted(path.iterdir()):
                if sub.is_dir() and not sub.name.startswith("."):
                    skills.append(parse_skill_folder(skills_dir, sub, is_third_party=False, category=path.name))

    return {"ok": True, "count": len(skills), "skills": skills}
