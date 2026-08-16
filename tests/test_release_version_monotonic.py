"""The published release and source tree may differ only by one pre-release step."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "release_published_check.py"


def _module() -> ModuleType:
    scripts_dir = str(SCRIPT.parent)
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)
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
    assert "strict vX.Y.Z contract" in capsys.readouterr().out


def test_source_and_release_tag_parsers_have_distinct_strict_contracts() -> None:
    module = _module()
    assert module.source_parts("4.169.47") == (4, 169, 47)
    assert module.source_parts("v4.169.47") == ()
    assert module.source_parts("04.169.47") == ()
    assert module.release_tag_parts("v4.169.47") == (4, 169, 47)
    assert module.release_tag_parts("4.169.47") == ()
    assert module.release_tag_parts("v04.169.47") == ()


def test_malformed_source_versions_fail_closed(capsys) -> None:
    for source in ("v4.169.47", "4.169", "4.x.47"):
        module = _module()
        module.current_version = lambda value=source: value
        module._api = lambda _path: _release("v4.169.47")
        assert module.main([]) == 1
    output = capsys.readouterr().out
    assert output.count("strict X.Y.Z contract") == 3


def test_malformed_latest_tags_cannot_bypass_the_release_gate(capsys) -> None:
    for latest_tag in ("4.169.47", "vv4.169.47", "v4.169", "v4.x.47"):
        module = _module()
        module.current_version = lambda: "4.169.47"
        # Deliberately omit the required alias: the malformed tag must never
        # reach an OK result merely because raw tag equality skipped assets.
        module._api = lambda _path, value=latest_tag: _release(value, alias=False)
        assert module.main([]) == 1
    output = capsys.readouterr().out
    assert output.count("strict vX.Y.Z contract") == 4


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
