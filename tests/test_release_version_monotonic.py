"""The published release and source tree may differ only by one pre-release step."""
from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "release_published_check.py"


def _module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("release_monotonic_probe", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _release(tag: str, *, alias: bool = True) -> dict:
    assets = [{"name": "arena-agent.zip"}] if alias else []
    return {"tag_name": tag, "assets": assets}


def test_latest_release_may_not_lead_the_source_tree(capsys) -> None:
    module = _module()
    module.current_version = lambda: "4.169.44"
    module._api = lambda _path: _release("v4.169.45")
    assert module.main([]) == 1
    assert "ahead of the source tree" in capsys.readouterr().out


def test_missing_or_malformed_latest_release_fails_closed(capsys) -> None:
    for latest in ({}, {"tag_name": "not-semver", "assets": []}):
        module = _module()
        module.current_version = lambda: "4.169.44"
        module._api = lambda _path, value=latest: value
        assert module.main([]) == 1
    assert "valid semantic version" in capsys.readouterr().out


def test_one_unpublished_candidate_is_allowed_only_in_non_strict_mode() -> None:
    module = _module()
    module.current_version = lambda: "4.169.45"
    module._api = lambda _path: _release("v4.169.44")
    assert module.main([]) == 0
    assert module.main(["--strict"]) == 1


def test_multiple_unpublished_versions_fail() -> None:
    module = _module()
    module.current_version = lambda: "4.169.46"
    module._api = lambda _path: _release("v4.169.44")
    assert module.main([]) == 1


def test_current_published_release_requires_alias_and_passes_with_it() -> None:
    module = _module()
    module.current_version = lambda: "4.169.44"
    module._api = lambda _path: _release("v4.169.44", alias=False)
    assert module.main([]) == 1
    module._api = lambda _path: _release("v4.169.44", alias=True)
    assert module.main([]) == 0
