"""The generator must prove full matrix and closure and check both locks."""
from __future__ import annotations

import io
from unittest import TestCase

import pytest

from arena import termux_requirements as refresh
from arena.termux_artifacts import usable_hashes
from arena.termux_validation import validate_closure

CHECK = TestCase()
VERSIONS = ("3.10", "3.11", "3.12", "3.13", "3.14")


def _artifact(filename, kind, requires, digest):
    return {"filename": filename, "packagetype": kind, "requires_python": requires,
            "digests": {"sha256": digest * 64}}


def test_partial_artifacts_must_cover_every_python() -> None:
    wheel = _artifact("demo-1.0-cp310-cp310-android_24_arm64_v8a.whl", "bdist_wheel", ">=3.10", "a")
    sdist = _artifact("demo-1.0.tar.gz", "sdist", ">=3.11", "b")
    CHECK.assertEqual(usable_hashes({"urls": [wheel]}, VERSIONS), [])
    CHECK.assertEqual(usable_hashes({"urls": [wheel, sdist]}, VERSIONS), ["a" * 64, "b" * 64])


def test_abi3_wheel_covers_newer_interpreters_but_not_older_ones() -> None:
    wheel = _artifact("demo-1.0-cp311-abi3-android_24_arm64_v8a.whl", "bdist_wheel", ">=3.10", "a")
    CHECK.assertEqual(usable_hashes({"urls": [wheel]}, VERSIONS), [])
    CHECK.assertEqual(usable_hashes({"urls": [wheel]}, VERSIONS[1:]), ["a" * 64])


@pytest.mark.parametrize("requirement", ["missing>=1", "demo>=2", 'missing; python_version < "3.11"'])
def test_closure_rejects_missing_or_incompatible_dependency(requirement) -> None:
    def fetch(url):
        return {"info": {"requires_dist": [requirement]}}
    with pytest.raises(RuntimeError, match="does not satisfy"):
        validate_closure([("demo", "1.0", ["a" * 64])], fetch, VERSIONS)


def test_closure_ignores_dependencies_inactive_on_every_target() -> None:
    def fetch(url):
        return {"info": {"requires_dist": ['missing; sys_platform == "win32"']}}
    validate_closure([("demo", "1.0", ["a" * 64])], fetch, VERSIONS)


def _generation(monkeypatch, tmp_path):
    main, optional = tmp_path / "main.txt", tmp_path / "optional.txt"
    rows, extras = [("demo", "1.0", ["a" * 64])], [("extra", "1.0", ["b" * 64])]
    monkeypatch.setattr(refresh, "TARGET", main)
    monkeypatch.setattr(refresh, "OPTIONAL_TARGET", optional)
    monkeypatch.setattr(refresh, "_collect_rows", lambda packages, optional=False: extras if optional else rows)
    monkeypatch.setattr(refresh, "_fetch", lambda url: {"info": {"requires_dist": []}})
    monkeypatch.setattr(refresh.sys, "argv", ["refresh", "--check"])
    main.write_text(refresh.render(rows))
    optional.write_text(refresh.render(extras, header=refresh.OPTIONAL_HEADER))
    return main, optional


def test_check_verifies_optional_lock_and_never_writes(monkeypatch, tmp_path) -> None:
    main, optional = _generation(monkeypatch, tmp_path)
    CHECK.assertEqual(refresh.main(), 0)
    original = main.read_bytes()
    optional.unlink()
    CHECK.assertEqual(refresh.main(), 1)
    CHECK.assertEqual(main.read_bytes(), original)
    CHECK.assertFalse(optional.exists())


@pytest.mark.parametrize("injection", ["--extra-index-url https://example.test\n", "unverified\n"])
def test_check_detects_injected_options_or_unpinned_requirements(monkeypatch, tmp_path, injection) -> None:
    main, _ = _generation(monkeypatch, tmp_path)
    main.write_text(main.read_text() + injection)
    CHECK.assertEqual(refresh.main(), 1)


def test_closure_failure_does_not_write_either_lock(monkeypatch, tmp_path) -> None:
    main, optional = _generation(monkeypatch, tmp_path)
    before = (main.read_bytes(), optional.read_bytes())
    monkeypatch.setattr(refresh.sys, "argv", ["refresh"])
    monkeypatch.setattr(refresh, "_fetch", lambda url: {"info": {"requires_dist": ["missing>=1"]}})
    CHECK.assertEqual(refresh.main(), 2)
    CHECK.assertEqual((main.read_bytes(), optional.read_bytes()), before)


def test_malformed_json_follows_controlled_collect_failure(monkeypatch, capsys) -> None:
    monkeypatch.setattr(refresh, "_open_pypi", lambda *args, **kwargs: io.BytesIO(b'not JSON'))
    CHECK.assertIsNone(refresh._collect_rows(("demo",)))
    CHECK.assertIn("FAILED", capsys.readouterr().err)


def test_fetch_preserves_stdlib_https_proxy_handling(monkeypatch) -> None:
    import urllib.request

    monkeypatch.setenv("HTTPS_PROXY", "http://proxy.example.test:8080")
    opener = refresh._pypi_opener()
    proxies = [handler.proxies.get("https") for handler in opener.handlers
               if isinstance(handler, urllib.request.ProxyHandler)]
    CHECK.assertIn("http://proxy.example.test:8080", proxies)
    calls = []
    def open_request(request, timeout):
        calls.append((request.full_url, timeout))
        return io.BytesIO(b'{}')
    monkeypatch.setattr(opener, "open", open_request)
    monkeypatch.setattr(refresh, "_pypi_opener", lambda: opener)
    CHECK.assertEqual(refresh._fetch("https://pypi.org/pypi/demo/json"), {})
    CHECK.assertEqual(calls, [("https://pypi.org/pypi/demo/json", refresh.TIMEOUT_S)])


@pytest.mark.parametrize("marker", ['sys_platform == "android"', 'python_version == "3.10"'])
def test_target_active_markers_cannot_use_runner_environment(marker) -> None:
    def fetch(url):
        return {"info": {"requires_dist": ["missing; " + marker]}}
    with pytest.raises(RuntimeError, match="does not satisfy"):
        validate_closure([("demo", "1.0", [])], fetch, VERSIONS)


@pytest.mark.parametrize("marker", ['python_full_version >= "3.11.4"',
                                    'implementation_version >= "3.11.4"'])
def test_unknown_patch_markers_block_generation(marker) -> None:
    def fetch(url):
        return {"info": {"requires_dist": ["missing; " + marker]}}
    with pytest.raises(RuntimeError, match="cannot prove"):
        validate_closure([("demo", "1.0", [])], fetch, VERSIONS)


@pytest.mark.parametrize("tag", ["cp314-cp314t", "cp314-cp313", "cp3-abi3", "cp3x-abi3"])
def test_incompatible_or_malformed_abi_cannot_supply_coverage(tag) -> None:
    wheel = _artifact("demo-1.0-" + tag + "-android_24_arm64_v8a.whl", "bdist_wheel", ">=3.10", "a")
    CHECK.assertEqual(usable_hashes({"urls": [wheel]}, ("3.14",)), [])


@pytest.mark.parametrize("url", ["https://evil.test/x", "http://pypi.org/x", "ftp://pypi.org/x",
                                 "https://pypi.org/pypi/redirected/json"])
@pytest.mark.parametrize("status", [301, 302, 303, 307, 308])
def test_redirect_cannot_supply_metadata(url, status) -> None:
    import urllib.error
    import urllib.request

    request = urllib.request.Request("https://pypi.org/pypi/demo/json")
    opener = refresh._pypi_opener()
    CHECK.assertFalse(any(isinstance(handler, urllib.request.HTTPRedirectHandler)
                          for handler in opener.handlers))
    with pytest.raises(urllib.error.HTTPError) as raised:
        opener.error("http", request, io.BytesIO(b'untrusted'), status, "Redirect", {"Location": url})
    CHECK.assertEqual(raised.value.code, status)


@pytest.mark.parametrize("metadata", [{}, {"info": {}}, {"info": {"requires_dist": "missing"}},
                                      {"info": {"requires_dist": [7]}}])
def test_unknown_dependency_metadata_fails_closed(metadata) -> None:
    with pytest.raises(RuntimeError, match="dependency metadata"):
        validate_closure([("demo", "1.0", [])], lambda url: metadata, VERSIONS)


def test_unbounded_abi_suffix_is_rejected_without_integer_conversion() -> None:
    wheel = _artifact("demo-1.0-cp3" + "9" * 5000 + "-abi3-android_24_arm64_v8a.whl",
                      "bdist_wheel", ">=3.10", "a")
    CHECK.assertEqual(usable_hashes({"urls": [wheel]}, ("3.14",)), [])


@pytest.mark.parametrize("platform", ["android_25_arm64_v8a", "android_37_arm64_v8a",
                                      "android_24_x86_64", "android_aarch64",
                                      "not_android_24_arm64_v8a", "android_0_aarch64"])
def test_wheel_only_release_above_api_floor_or_wrong_platform_is_unusable(platform):
    from arena.termux_artifacts import usable_hashes
    wheel = _artifact(f"demo-1.0-py3-none-{platform}.whl", "bdist_wheel", ">=3.10", "a")
    assert usable_hashes({"info": {}, "urls": [wheel]}, ("3.10",)) == []
