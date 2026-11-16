"""The generated Termux lock must remain installable at Python 3.10+."""
from __future__ import annotations

from typing import Any

import pytest

from arena import termux_requirements as refresh


def _file(version: str, *, yanked: bool = False) -> dict[str, Any]:
    return {"filename": f"multidict-{version}.tar.gz", "packagetype": "sdist",
            "yanked": yanked}


def _detail(version: str, requires_python: str, digest: str) -> dict[str, Any]:
    return {"info": {"requires_python": requires_python},
            "urls": [{"filename": f"multidict-{version}.tar.gz",
                      "packagetype": "sdist", "yanked": False,
                      "digests": {"sha256": digest}}]}


def test_candidate_order_excludes_prereleases() -> None:
    releases = {
        "7.3.0rc1": [_file("7.3.0rc1")],
        "7.2.0": [_file("7.2.0")],
    }
    candidates = refresh._candidate_versions(releases)
    if candidates != ["7.2.0"]:
        raise AssertionError(f"prerelease candidate was not excluded: {candidates}")


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

    if refresh.collect("multidict") != ("7.1.0", ["c" * 64]):
        raise AssertionError("the resolver did not fall back to the newest usable release")


def test_skips_yanked_newer_release(monkeypatch) -> None:
    project = {"releases": {
        "7.2.1": [_file("7.2.1", yanked=True)],
        "7.1.0": [_file("7.1.0")],
    }}
    detail = _detail("7.1.0", ">=3.10", "c" * 64)
    monkeypatch.setattr(refresh, "_fetch",
                        lambda url: project if url.endswith("/multidict/json")
                        else detail)

    if refresh.collect("multidict") != ("7.1.0", ["c" * 64]):
        raise AssertionError("the resolver did not skip the yanked newer release")



def test_refuses_to_write_when_no_release_is_supported_and_installable(monkeypatch) -> None:
    project = {"releases": {
        "7.2.1": [_file("7.2.1", yanked=True)],
        "7.1.0": [_file("7.1.0")],
    }}
    detail = _detail("7.1.0", ">=3.15", "c" * 64)
    monkeypatch.setattr(
        refresh,
        "_fetch",
        lambda url: project if url.endswith("/multidict/json") else detail,
    )

    with pytest.raises(RuntimeError, match="no non-yanked release with usable artifacts"):
        refresh.collect("multidict")


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


@pytest.mark.parametrize("artifact_python", [">=3.11", ">=3.10,<3.14", ">=>3.10"])
def test_rejects_incompatible_artifact_even_when_release_metadata_allows_it(
    monkeypatch, artifact_python: str,
) -> None:
    project = {"releases": {"7.2.0": [_file("7.2.0")], "7.1.0": [_file("7.1.0")]}}
    newer = _detail("7.2.0", ">=3.10", "a" * 64)
    newer["urls"][0]["requires_python"] = artifact_python
    older = _detail("7.1.0", ">=3.10", "b" * 64)
    details = {"7.2.0": newer, "7.1.0": older}
    monkeypatch.setattr(refresh, "_fetch", lambda url: project if url.endswith("/multidict/json")
                        else details[url.split("/")[-2]])
    assert refresh.collect("multidict") == ("7.1.0", ["b" * 64])


def test_hashes_keep_compatible_artifacts_and_exclude_incompatible_ones() -> None:
    detail = _detail("7.2.0", ">=3.10", "a" * 64)
    incompatible = dict(detail["urls"][0], requires_python=">=3.11",
                        digests={"sha256": "b" * 64})
    detail["urls"].append(incompatible)
    assert refresh._usable_hashes(detail) == ["a" * 64]
