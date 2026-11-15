"""The generated Termux lock must remain installable at Python 3.10+."""
from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "refresh_termux_requirements.py"
spec = importlib.util.spec_from_file_location("refresh_termux_requirements", SCRIPT)
assert spec and spec.loader
refresh = importlib.util.module_from_spec(spec)
spec.loader.exec_module(refresh)


def _file(version: str, *, yanked: bool = False) -> dict[str, object]:
    return {"filename": f"multidict-{version}.tar.gz", "packagetype": "sdist",
            "yanked": yanked}


def _detail(version: str, requires_python: str, digest: str) -> dict[str, object]:
    return {"info": {"requires_python": requires_python},
            "urls": [{"filename": f"multidict-{version}.tar.gz",
                      "packagetype": "sdist", "yanked": False,
                      "digests": {"sha256": digest}}]}


def test_selects_latest_release_compatible_with_python_floor(monkeypatch) -> None:
    project = {"releases": {
        "7.2.1": [_file("7.2.1")],
        "7.1.0": [_file("7.1.0")],
    }}
    details = {
        "https://pypi.org/pypi/multidict/7.2.1/json": _detail("7.2.1", ">=3.11", "a" * 64),
        "https://pypi.org/pypi/multidict/7.1.0/json": _detail("7.1.0", ">=3.10", "b" * 64),
    }
    monkeypatch.setattr(refresh, "_fetch",
                        lambda url: project if url.endswith("/json") and url.endswith("/multidict/json")
                        else details[url])

    assert refresh.collect("multidict") == ("7.1.0", ["b" * 64])


def test_skips_yanked_newer_release(monkeypatch) -> None:
    project = {"releases": {
        "7.2.1": [_file("7.2.1", yanked=True)],
        "7.1.0": [_file("7.1.0")],
    }}
    detail = _detail("7.1.0", ">=3.10", "c" * 64)
    monkeypatch.setattr(refresh, "_fetch",
                        lambda url: project if url.endswith("/multidict/json")
                        else detail)

    assert refresh.collect("multidict") == ("7.1.0", ["c" * 64])


def test_skips_release_that_excludes_a_newer_supported_python(monkeypatch) -> None:
    project = {"releases": {
        "7.3.0": [_file("7.3.0")],
        "7.1.0": [_file("7.1.0")],
    }}
    details = {
        "https://pypi.org/pypi/multidict/7.3.0/json": _detail(
            "7.3.0", ">=3.10,<3.14", "d" * 64),
        "https://pypi.org/pypi/multidict/7.1.0/json": _detail(
            "7.1.0", ">=3.10", "e" * 64),
    }
    monkeypatch.setattr(refresh, "_fetch",
                        lambda url: project if url.endswith("/multidict/json")
                        else details[url])

    assert refresh.collect("multidict") == ("7.1.0", ["e" * 64])


def test_malformed_requires_python_skips_candidate(monkeypatch) -> None:
    project = {"releases": {
        "7.3.1": [_file("7.3.1")],
        "7.1.0": [_file("7.1.0")],
    }}
    details = {
        "https://pypi.org/pypi/multidict/7.3.1/json": _detail(
            "7.3.1", ">=>3.10", "b" * 64),
        "https://pypi.org/pypi/multidict/7.1.0/json": _detail(
            "7.1.0", ">=3.10", "c" * 64),
    }
    monkeypatch.setattr(refresh, "_fetch",
                        lambda url: project if url.endswith("/multidict/json")
                        else details[url])

    assert refresh.collect("multidict") == ("7.1.0", ["c" * 64])


def test_yanked_artifacts_are_never_included_in_hashes(monkeypatch) -> None:
    project = {"releases": {"7.2.1": [_file("7.2.1")]}}
    detail = _detail("7.2.1", ">=3.10", "f" * 64)
    detail["urls"].append({
        "filename": "multidict-7.2.1-cp313-cp313-android_aarch64.whl",
        "packagetype": "bdist_wheel", "yanked": True,
        "digests": {"sha256": "a" * 64},
    })
    monkeypatch.setattr(refresh, "_fetch",
                        lambda url: project if url.endswith("/multidict/json")
                        else detail)

    assert refresh.collect("multidict") == ("7.2.1", ["f" * 64])
