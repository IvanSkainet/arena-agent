"""Compatibility/runtime wrappers around skill registry/install/runner helpers."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from arena.skills.install import install_skill, normalize_third_party_skill_name, uninstall_skill
from arena.skills.registry import parse_skill_folder, scan_skills
from arena.skills.runner import run_skill


@dataclass(frozen=True)
class SkillRuntimeContext:
    skills_dir: Path
    root_agent: Path
    bin_dir: Path
    subprocess_kwargs: Callable[[], dict[str, Any]]


@dataclass(frozen=True)
class SkillRuntime:
    skills_list_sync: Callable[[], dict[str, Any]]
    parse_skill_folder_compat: Callable[..., None]
    skill_install_sync: Callable[[str, str], dict[str, Any]]
    normalize_third_party_skill_name: Callable[[str], tuple[str | None, str | None]]
    skill_uninstall_sync: Callable[[str], dict[str, Any]]
    skills_run_sync: Callable[..., dict[str, Any]]
    skill_path_is_safe: Callable[[str], bool]


def make_skill_runtime(ctx: SkillRuntimeContext) -> SkillRuntime:
    def _skills_list_sync() -> dict[str, Any]:
        return scan_skills(ctx.skills_dir)

    def _parse_skill_folder(d: Path, skills: list, is_third_party: bool = False, category: str = "") -> None:
        skills.append(parse_skill_folder(ctx.skills_dir, d, is_third_party=is_third_party, category=category))

    def _skill_install_sync(name: str, url: str) -> dict[str, Any]:
        return install_skill(name, url, skills_dir=ctx.skills_dir)

    def _normalize_third_party_skill_name(name: str) -> tuple[str | None, str | None]:
        return normalize_third_party_skill_name(name)

    def _skill_uninstall_sync(name: str) -> dict[str, Any]:
        return uninstall_skill(name, skills_dir=ctx.skills_dir)

    def _skills_run_sync(name: str, args: list[str], env_extra: dict | None = None) -> dict[str, Any]:
        return run_skill(
            name,
            args,
            skills_dir=ctx.skills_dir,
            root_agent=ctx.root_agent,
            bin_dir=ctx.bin_dir,
            subprocess_kwargs_fn=ctx.subprocess_kwargs,
            env_extra=env_extra,
        )

    def _skill_path_is_safe(name: str) -> bool:
        try:
            resolved = (ctx.skills_dir / name).resolve()
            return str(resolved).startswith(str(ctx.skills_dir.resolve()))
        except Exception:
            return False

    return SkillRuntime(
        skills_list_sync=_skills_list_sync,
        parse_skill_folder_compat=_parse_skill_folder,
        skill_install_sync=_skill_install_sync,
        normalize_third_party_skill_name=_normalize_third_party_skill_name,
        skill_uninstall_sync=_skill_uninstall_sync,
        skills_run_sync=_skills_run_sync,
        skill_path_is_safe=_skill_path_is_safe,
    )
