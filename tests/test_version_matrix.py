"""Guards for ``tests/_version_matrix.py`` — the central release list.

If this file drifts out of sync with ``arena/constants.py`` or with
``pyproject.toml``, every version-pin extension test will start failing
in confusing ways. Fail loudly here so the release bump script owner
knows exactly what to fix.
"""
from __future__ import annotations

from pathlib import Path

from arena import constants

from tests._version_matrix import (
    BRIDGE_VERSIONS,
    EXT_VERSIONS,
    LATEST_BRIDGE,
    LATEST_EXT,
    any_bridge_in,
    any_pyproject_in,
    constants_snippets,
    pyproject_snippets,
)


REPO_ROOT = Path(__file__).resolve().parents[1]


def _read(rel: str) -> str:
    return (REPO_ROOT / rel).read_text(encoding="utf-8")


def test_latest_bridge_matches_constants_module():
    """``LATEST_BRIDGE`` must equal the running ``arena.constants.VERSION``.

    If they diverge the bump script forgot to update one side.
    """
    assert (
        LATEST_BRIDGE == constants.VERSION
    ), (
        f"tests/_version_matrix.LATEST_BRIDGE={LATEST_BRIDGE!r} "
        f"but arena.constants.VERSION={constants.VERSION!r}"
    )


def test_bridge_versions_ordered_and_unique():
    """Order (oldest first, latest last) and uniqueness invariants."""
    assert len(set(BRIDGE_VERSIONS)) == len(BRIDGE_VERSIONS)
    # crude ordering — split on '.' and compare integer triples
    triples = [tuple(int(x) for x in v.split(".")) for v in BRIDGE_VERSIONS]
    assert triples == sorted(triples)


def test_ext_versions_unique():
    assert len(set(EXT_VERSIONS)) == len(EXT_VERSIONS)


def test_latest_ext_matches_manifest():
    import json

    manifest = json.loads(_read("chat_extension/manifest.json"))
    assert LATEST_EXT == manifest["version"], (
        f"LATEST_EXT={LATEST_EXT!r} but chat_extension/manifest.json version={manifest['version']!r}"
    )


def test_any_bridge_in_matches_constants_source():
    """``any_bridge_in`` should positively detect the shipped version."""
    src = _read("arena/constants.py")
    assert any_bridge_in(src), (
        "constants.py source does not contain any accepted VERSION literal — "
        "did the bump script update BRIDGE_VERSIONS?"
    )


def test_any_pyproject_in_matches_pyproject_source():
    src = _read("pyproject.toml")
    assert any_pyproject_in(src), (
        "pyproject.toml does not contain any accepted version literal"
    )


def test_snippet_helpers_return_all_versions():
    csnips = constants_snippets()
    psnips = pyproject_snippets()
    assert len(csnips) == len(BRIDGE_VERSIONS)
    assert len(psnips) == len(BRIDGE_VERSIONS)
    for v in BRIDGE_VERSIONS:
        assert f'VERSION = "{v}"' in csnips
        assert f'version = "{v}"' in psnips
