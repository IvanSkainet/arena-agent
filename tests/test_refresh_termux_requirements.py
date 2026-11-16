"""The generated Termux lock must remain installable at Python 3.10+."""
from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any

import pytest  # pyright: ignore[reportMissingImports]

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "refresh_termux_requirements.py"
spec = importlib.util.spec_from_file_location("refresh_termux_requirements", SCRIPT)
assert spec and spec.loader  # nosec B101 -- pytest assertion
refresh = importlib.util.module_from_spec(spec)
spec.loader.exec_module(refresh)


def _file(version: str, *, yanked: bool = False) -> dict[str, Any]:
    return {"filename": f"multidict-{version}.tar.gz", "packagetype": "sdist",
            "yanked": yanked}


def _detail(version: str, requires_python: str, digest: str) -> dict[str, Any]:
    return {"info": {"requires_python": requires_python},
            "urls": [{"filename": f"multidict-{version}.tar.gz",
                      "packagetype": "sdist", "yanked": False,
                      "digests": {"sha256": digest}}]}


@pytest.mark.parametrize("case", [
    ("7.2.1", ">=3.11", "a", False),
    ("7.3.0", ">=3.10,<3.14", "d", False),
    ("7.3.1", ">=>3.10", "b", False),
    ("7.3.2", ">=3.10", "e", True),
])
def test_skips_candidate_without_supported_python_or_installable_artifact(
    monkeypatch, case: tuple[str, str, str, bool],
) -> None:
    candidate, requires_python, digest, manylinux_only = case
    project = {"releases": {
        candidate: [_file(candidate)],
        "7.1.0": [_file("7.1.0")],
    }}
    details = {
        f"https://pypi.org/pypi/multidict/{candidate}/json": _detail(
            candidate, requires_python, digest * 64),
        "https://pypi.org/pypi/multidict/7.1.0/json": _detail(
            "7.1.0", ">=3.10", "c" * 64),
    }
    if manylinux_only:
        details[f"https://pypi.org/pypi/multidict/{candidate}/json"]["urls"] = [{
            "filename": f"multidict-{candidate}-cp313-cp313-manylinux_2_17_aarch64.whl",
            "packagetype": "bdist_wheel", "yanked": False,
            "digests": {"sha256": digest * 64},
        }]
    monkeypatch.setattr(refresh, "_fetch",
                        lambda url: project if url.endswith("/multidict/json")
                        else details[url])

    assert refresh.collect("multidict") == ("7.1.0", ["c" * 64])  # nosec B101 -- pytest assertion


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



def test_relevant_wheels_are_termux_installable_not_glibc_only() -> None:
    assert refresh._relevant(  # nosec B101 -- pytest assertion
        "multidict-7.2.1-cp313-cp313-android_24_arm64_v8a.whl",
        "bdist_wheel",
    )
    assert refresh._relevant("multidict-7.2.1-py3-none-any.whl", "bdist_wheel")  # nosec B101 -- pytest assertion
    assert not refresh._relevant(  # nosec B101 -- pytest assertion
        "multidict-7.2.1-cp313-cp313-manylinux_2_17_aarch64.whl",
        "bdist_wheel",
    )


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

    assert refresh.collect("multidict") == ("7.2.1", ["f" * 64])  # nosec B101 -- pytest assertion
