"""T68: SECURITY.md must classify every exact ARENA_* source reference."""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from arena.governance.security_env_inventory import (
    SecurityEnvInventoryError,
    documented_inventory,
    source_references,
    verify_inventory,
)

ROOT = Path(__file__).resolve().parents[1]
START = "<!-- security-env-inventory:start -->"
END = "<!-- security-env-inventory:end -->"


def _table(*rows: str) -> str:
    body = [
        START,
        "| Variable | Classification | Default | Effect |",
        "|---|---|---|---|",
        *rows,
        END,
    ]
    return "\n".join(body)


def _row(name: str, classification: str = "security") -> str:
    return f"| `{name}` | {classification} | exact | Test effect. |"


def test_real_security_inventory_matches_source_exactly() -> None:
    verify_inventory(ROOT, ROOT / "SECURITY.md")
    source = source_references(ROOT)
    documented = documented_inventory(ROOT.joinpath("SECURITY.md").read_text(encoding="utf-8"))
    assert set(source) == set(documented)
    assert len(source) == 75


def test_security_weakening_and_credential_inputs_are_classified() -> None:
    inventory = documented_inventory(ROOT.joinpath("SECURITY.md").read_text(encoding="utf-8"))
    required_security = {
        "ARENA_ASSUME_SYSTEMD_FENCE",
        "ARENA_AUTO_BIND",
        "ARENA_BREAKER_DISABLE",
        "ARENA_INPUT_HELPER_TOKEN",
        "ARENA_LOCAL_BRIDGE_TOKEN",
        "ARENA_PROFILE",
        "ARENA_SCENARIOS_ALLOW_YAML",
        "ARENA_SECRETS_PATH",
        "ARENA_UPDATE_REPO",
        "ARENA_UPDATE_ROOT",
    }
    assert {name: inventory[name] for name in required_security} == {
        name: "security" for name in required_security
    }


def test_source_scanner_records_exact_names_and_paths(tmp_path: Path) -> None:
    source_root = tmp_path / "arena"
    source_root.mkdir()
    source_root.joinpath("sample.py").write_text(
        'VALUE = "ARENA_EXACT_NAME"\n'
        'MESSAGE = "ARENA_NOT_EXACT is disabled"\n'
        'LOWER = "arena_ignored"\n',
        encoding="utf-8",
    )
    scripts_root = tmp_path / "scripts"
    scripts_root.mkdir()
    scripts_root.joinpath("helper.py").write_text(
        'VALUE = "ARENA_SCRIPT_EXACT"\n', encoding="utf-8"
    )
    bin_root = tmp_path / "bin"
    bin_root.mkdir()
    bin_root.joinpath("command.py").write_text(
        'VALUE = "ARENA_BIN_EXACT"\n', encoding="utf-8"
    )
    skills_root = tmp_path / "skills"
    skills_root.mkdir()
    skills_root.joinpath("run.py").write_text(
        'VALUE = "ARENA_SKILL_EXACT"\n', encoding="utf-8"
    )
    tmp_path.joinpath("root_tool.py").write_text(
        'VALUE = "ARENA_ROOT_EXACT"\n', encoding="utf-8"
    )
    assert source_references(tmp_path) == {
        "ARENA_BIN_EXACT": ("bin/command.py",),
        "ARENA_EXACT_NAME": ("arena/sample.py",),
        "ARENA_ROOT_EXACT": ("root_tool.py",),
        "ARENA_SCRIPT_EXACT": ("scripts/helper.py",),
        "ARENA_SKILL_EXACT": ("skills/run.py",),
    }


@pytest.mark.parametrize("symlink_kind", ["file", "directory", "root-file"])
def test_symlinked_source_fails_closed(
    tmp_path: Path, monkeypatch, symlink_kind: str
) -> None:
    source_root = tmp_path / "arena"
    source_root.mkdir()
    source = source_root / "linked.py"
    source.write_text('FLAG = "ARENA_LINKED"\n', encoding="utf-8")
    if symlink_kind == "file":
        rejected = source
    elif symlink_kind == "directory":
        rejected = source_root
    else:
        rejected = tmp_path / "root_linked.py"
        rejected.write_text('FLAG = "ARENA_ROOT_LINKED"\n', encoding="utf-8")
    original = Path.is_symlink
    monkeypatch.setattr(
        Path, "is_symlink", lambda path: path == rejected or original(path)
    )
    with pytest.raises(SecurityEnvInventoryError) as caught:
        source_references(tmp_path)
    assert str(caught.value) == f"symlinked Python source: {rejected}"


@pytest.mark.skipif(os.name == "nt", reason="Windows symlink creation needs elevation")
@pytest.mark.parametrize("symlink_kind", ["file", "directory", "dangling"])
def test_actual_nested_symlinks_fail_closed(
    tmp_path: Path, symlink_kind: str
) -> None:
    source_root = tmp_path / "arena"
    source_root.mkdir()
    target = tmp_path / "target"
    link = source_root / "linked"
    if symlink_kind == "file":
        target.write_text('FLAG = "ARENA_LINKED"\n', encoding="utf-8")
        link = link.with_suffix(".py")
        link.symlink_to(target)
    elif symlink_kind == "directory":
        target.mkdir()
        target.joinpath("inside.py").write_text(
            'FLAG = "ARENA_LINKED"\n', encoding="utf-8"
        )
        link.symlink_to(target, target_is_directory=True)
    else:
        link.symlink_to(target, target_is_directory=True)

    with pytest.raises(SecurityEnvInventoryError) as caught:
        source_references(tmp_path)
    assert str(caught.value) == f"symlinked Python source: {link}"


@pytest.mark.parametrize(
    "source_names, documented_names, expected",
    [
        (
            ("ARENA_LIVE", "ARENA_MISSING"),
            ("ARENA_LIVE",),
            "undocumented source references: ARENA_MISSING "
            + "(arena/sample.py, scripts/helper.py)",
        ),
        (
            ("ARENA_LIVE",),
            ("ARENA_LIVE", "ARENA_STALE"),
            "stale documented references: ARENA_STALE",
        ),
        (
            ("ARENA_UNDOCUMENTED_FIRST", "ARENA_UNDOCUMENTED_SECOND"),
            ("ARENA_STALE_FIRST", "ARENA_STALE_SECOND"),
            "undocumented source references: ARENA_UNDOCUMENTED_FIRST "
            + "(arena/sample.py), ARENA_UNDOCUMENTED_SECOND (arena/sample.py); "
            + "stale documented references: ARENA_STALE_FIRST, ARENA_STALE_SECOND",
        ),
    ],
)
def test_inventory_drift_fails_closed(
    tmp_path: Path,
    source_names: tuple[str, ...],
    documented_names: tuple[str, ...],
    expected: str,
) -> None:
    source_root = tmp_path / "arena"
    source_root.mkdir()
    source_root.joinpath("sample.py").write_text(
        "\n".join(f'{name} = "{name}"' for name in source_names) + "\n",
        encoding="utf-8",
    )
    if "ARENA_MISSING" in source_names:
        scripts_root = tmp_path / "scripts"
        scripts_root.mkdir()
        scripts_root.joinpath("helper.py").write_text(
            'VALUE = "ARENA_MISSING"\n', encoding="utf-8"
        )
    security = tmp_path / "SECURITY.md"
    security.write_text(
        _table(*(_row(name) for name in documented_names)),
        encoding="utf-8",
    )
    with pytest.raises(SecurityEnvInventoryError) as caught:
        verify_inventory(tmp_path, security)
    assert str(caught.value) == expected


def test_inventory_rows_accept_markdown_whitespace() -> None:
    text = _table("  |  `ARENA_SPACED`  |  operational  |  exact  |  Effect.  |  ")
    assert documented_inventory(text) == {"ARENA_SPACED": "operational"}


@pytest.mark.parametrize(
    "text, expected",
    [
        ("", "SECURITY.md inventory markers must occur exactly once"),
        (
            f"{START}\n{START}\n{END}",
            "SECURITY.md inventory markers must occur exactly once",
        ),
        (
            f"{START}\n{END}\n{END}",
            "SECURITY.md inventory markers must occur exactly once",
        ),
        (f"{END}\n{START}", "SECURITY.md inventory markers are reversed"),
        (f"{START}\n{END}", "SECURITY.md environment inventory is empty"),
        (
            _table("| `ARENA_BAD` | unknown | exact | Effect. |"),
            "malformed SECURITY.md inventory row: "
            + "| `ARENA_BAD` | unknown | exact | Effect. |",
        ),
        (
            _table(_row("ARENA_PREFIX_")),
            "SECURITY.md exact/prefix classification mismatch: ARENA_PREFIX_",
        ),
        (
            _table("| `ARENA_EXACT` | operational | prefix | Effect. |"),
            "SECURITY.md exact/prefix classification mismatch: ARENA_EXACT",
        ),
        (
            _table(
                _row("ARENA_CONFLICT"),
                " |`ARENA_CONFLICT`|unknown|exact|Conflicting effect.|",
            ),
            "malformed SECURITY.md inventory row: "
            + " |`ARENA_CONFLICT`|unknown|exact|Conflicting effect.|",
        ),
        (
            _table(_row("ARENA_DUPLICATE"), _row("ARENA_DUPLICATE")),
            "duplicate SECURITY.md inventory row: ARENA_DUPLICATE",
        ),
    ],
)
def test_malformed_inventory_fails_closed(text: str, expected: str) -> None:
    with pytest.raises(SecurityEnvInventoryError) as caught:
        documented_inventory(text)
    assert str(caught.value) == expected
