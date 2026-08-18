"""T64: Git skill sources must not inherit executable Git transports."""
from __future__ import annotations

import os
import stat
from dataclasses import FrozenInstanceError
from types import SimpleNamespace

import pytest

import arena.skills.git_source as policy
import arena.skills.install as install


def _resolved_source(url: str) -> policy.ResolvedGitSource:
    return policy.ResolvedGitSource(
        url=url,
        host="example.com",
        port=443,
        addresses=("93.184.216.34", "2001:db8::34"),
    )


@pytest.mark.parametrize(
    "url",
    [
        "ext::sh -c whoami",
        "file:///tmp/repository",
        "ssh://git@example.com/repository",
        "git://example.com/repository",
        "C:/local/repository",
        "example.com/repository",
    ],
)
def test_non_http_git_transports_are_rejected_without_resolution(url):
    assert policy.validate_git_source_url(url) == (
        "git source scheme not allowed (only http/https)"
    )


@pytest.mark.parametrize(
    "url",
    [
        "https://user@example.com/repository",
        "https://user:secret@example.com/repository",
        "http://user@example.com/repository",
    ],
)
def test_credentials_are_rejected_before_resolution(url):
    assert policy.validate_git_source_url(url) == (
        "credentials in git source URL are not allowed"
    )


def test_missing_host_and_invalid_ports_are_structured():
    assert policy.validate_git_source_url("https:///repository") == (
        "git source host is required"
    )
    for url in (
        "https://example.com:0/repository",
        "https://example.com:/repository",
    ):
        assert policy.validate_git_source_url(url) == (
            "git source port is invalid"
        )
    assert policy.validate_git_source_url("https://example.com:99999/repository") == (
        "invalid git source URL"
    )


def test_public_http_and_https_static_sources_are_accepted():
    assert policy.validate_git_source_url("https://example.com/repository") is None
    assert policy.validate_git_source_url("http://example.com:8080/repository") is None
    assert policy.validate_git_source_url("https://example.com:1/repository") is None


def test_resolve_rejects_static_error_before_dns(monkeypatch):
    monkeypatch.setattr(
        policy,
        "_public_addresses",
        lambda _url: pytest.fail("static rejection reached DNS"),
    )
    source, error = policy.resolve_git_source_url("ext::echo bypass")
    assert source is None
    assert error == "git source scheme not allowed (only http/https)"


def test_git_source_is_resolved_once_and_pinned_for_curl(monkeypatch):
    calls = []

    def resolve(url):
        calls.append(url)
        return (
            policy.urlparse(url),
            "example.com",
            ("93.184.216.34", "2001:db8::34"),
        )

    monkeypatch.setattr(policy, "_public_addresses", resolve)
    source, error = policy.resolve_git_source_url(
        "https://Example.COM.:8443/repository"
    )
    assert error is None
    assert source == policy.ResolvedGitSource(
        url="https://example.com:8443/repository",
        host="example.com",
        port=8443,
        addresses=("93.184.216.34", "2001:db8::34"),
    )
    assert source is not None
    assert source.curl_resolve_values() == (
        "example.com:8443:93.184.216.34",
        "example.com:8443:[2001:db8::34]",
    )
    assert calls == ["https://Example.COM.:8443/repository"]
    with pytest.raises(FrozenInstanceError):
        source.port = 443  # type: ignore[reportAttributeAccessIssue]


def test_default_ports_and_ipv6_authority_are_preserved(monkeypatch):
    answers = {
        "https://example.com/repository": (
            "example.com", ("93.184.216.34",)
        ),
        "http://example.com/repository": (
            "example.com", ("93.184.216.34",)
        ),
        "https://[2001:4860:4860::8888]/repository": (
            "2001:4860:4860::8888", ("2001:4860:4860::8888",)
        ),
    }

    def resolve(url):
        host, addresses = answers[url]
        return policy.urlparse(url), host, addresses

    monkeypatch.setattr(policy, "_public_addresses", resolve)
    https_source, _ = policy.resolve_git_source_url(
        "https://example.com/repository"
    )
    http_source, _ = policy.resolve_git_source_url(
        "http://example.com/repository"
    )
    ipv6_source, _ = policy.resolve_git_source_url(
        "https://[2001:4860:4860::8888]/repository"
    )
    assert https_source is not None
    assert https_source.port == 443
    assert http_source is not None
    assert http_source.port == 80
    assert ipv6_source is not None
    assert ipv6_source.url == "https://[2001:4860:4860::8888]/repository"
    assert ipv6_source.port == 443
    assert ipv6_source.curl_resolve_values() == ()


def test_literal_source_needs_no_curl_dns_override(monkeypatch):
    monkeypatch.setattr(
        policy,
        "_public_addresses",
        lambda url: (policy.urlparse(url), "8.8.8.8", ("8.8.8.8",)),
    )
    source, error = policy.resolve_git_source_url(
        "https://8.8.8.8/repository"
    )
    assert error is None
    assert source is not None
    assert source.curl_resolve_values() == ()


def test_resolution_failure_is_structured(monkeypatch):
    def reject(_url):
        raise OSError("host resolves to a private/internal address")

    monkeypatch.setattr(policy, "_public_addresses", reject)
    source, error = policy.resolve_git_source_url(
        "https://internal.test/repository"
    )
    assert source is None
    assert error == (
        "git source rejected: host resolves to a private/internal address"
    )


def test_readonly_tree_cleanup_is_fail_closed(tmp_path, monkeypatch):
    metadata = tmp_path / ".git"
    metadata.mkdir()
    locked = metadata / "locked"
    locked.write_text("x", encoding="utf-8")
    locked.chmod(stat.S_IREAD)
    assert policy.remove_tree_readonly(metadata) is True
    assert not metadata.exists()
    assert policy.remove_tree_readonly(metadata) is True

    failed = tmp_path / "failed"
    failed.mkdir()
    monkeypatch.setattr(
        policy.shutil,
        "rmtree",
        lambda *_a, **_k: (_ for _ in ()).throw(OSError("denied")),
    )
    assert policy.remove_tree_readonly(failed) is False


def test_readonly_cleanup_callback_retries_exact_path_and_mode(tmp_path, monkeypatch):
    tree = tmp_path / "tree"
    tree.mkdir()
    locked = tree / "locked"
    locked.write_text("x", encoding="utf-8")
    original_rmtree = policy.shutil.rmtree
    chmod_calls = []
    retry_calls = []

    def fake_rmtree(path, *, onerror):
        onerror(
            lambda value: retry_calls.append(value),
            locked,
            None,
        )
        original_rmtree(path)

    monkeypatch.setattr(policy.shutil, "rmtree", fake_rmtree)
    monkeypatch.setattr(
        policy.os,
        "chmod",
        lambda value, mode: chmod_calls.append((value, mode)),
    )
    assert policy.remove_tree_readonly(tree) is True
    assert chmod_calls == [
        (locked, stat.S_IREAD | stat.S_IWRITE | stat.S_IEXEC)
    ]
    assert retry_calls == [locked]


def test_git_environment_overrides_and_removes_config_injection():
    result = policy.git_protocol_environment({
        "PATH": "bin",
        "GIT_ALLOW_PROTOCOL": "ext:file:ssh",
        "GIT_PROTOCOL_FROM_USER": "1",
        "GIT_CONFIG_COUNT": "2",
        "GIT_CONFIG_KEY_0": "protocol.ext.allow",
        "GIT_CONFIG_VALUE_0": "always",
        "GIT_CONFIG_KEY_1": "protocol.file.allow",
        "GIT_CONFIG_VALUE_1": "always",
        "GIT_SSH_COMMAND": "ssh-custom",
        "GIT_SSL_NO_VERIFY": "1",
        "GIT_CONFIG_PARAMETERS": "'url.http://internal/.insteadOf=https://example.com/'",
        "GIT_CONFIG_GLOBAL": "host-global-config",
        "GIT_CONFIG_SYSTEM": "host-system-config",
    })
    assert result == {
        "PATH": "bin",
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CONFIG_SYSTEM": os.devnull,
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_ALLOW_PROTOCOL": "https:http",
        "GIT_PROTOCOL_FROM_USER": "0",
        "GIT_TERMINAL_PROMPT": "0",
    }


def test_install_git_source_uses_exact_transport_environment(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(
        install,
        "resolve_git_source_url",
        lambda url: (_resolved_source(url), None),
    )
    monkeypatch.setattr(
        install,
        "git_protocol_environment",
        lambda environ: {"SAFE": str(environ is os.environ)},
    )

    def run(argv, **kwargs):
        calls.append((argv, kwargs))
        target = tmp_path / "third_party" / "demo"
        (target / ".git").mkdir(parents=True)
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(install.shutil, "which", lambda name: "/usr/bin/git")
    monkeypatch.setattr(install.subprocess, "run", run)
    result = install.install_skill(
        "demo", "https://example.com/demo", skills_dir=tmp_path
    )
    target = tmp_path / "third_party" / "demo"
    assert result == {"ok": True, "path": str(target), "name": "demo"}
    assert target.is_dir()
    assert not (target / ".git").exists()
    assert calls == [
        ([
            "/usr/bin/git",
            "-c", "protocol.allow=never",
            "-c", "protocol.http.allow=always",
            "-c", "protocol.https.allow=always",
            "-c", "http.followRedirects=false",
            "-c", "http.curloptResolve=+example.com:443:93.184.216.34",
            "-c", "http.curloptResolve=+example.com:443:[2001:db8::34]",
            "clone", "--depth", "1", "--",
            "https://example.com/demo", str(target),
        ], {
            "check": False,
            "capture_output": True,
            "env": {"SAFE": "True"},
            "timeout": 60,
        })
    ]


def test_install_fails_if_git_metadata_cannot_be_removed(tmp_path, monkeypatch):
    monkeypatch.setattr(
        install,
        "resolve_git_source_url",
        lambda url: (_resolved_source(url), None),
    )
    monkeypatch.setattr(install.shutil, "which", lambda _name: "/usr/bin/git")

    def run(*_args, **_kwargs):
        target = tmp_path / "third_party" / "locked"
        (target / ".git").mkdir(parents=True)
        return SimpleNamespace(returncode=0)

    cleanup_calls = []

    def cleanup(path):
        cleanup_calls.append(path)
        return path.name != ".git"

    monkeypatch.setattr(install.subprocess, "run", run)
    monkeypatch.setattr(install, "remove_tree_readonly", cleanup)
    result = install.install_skill(
        "locked", "https://example.com/repository", skills_dir=tmp_path
    )
    target = tmp_path / "third_party" / "locked"
    assert result == {"ok": False, "error": "git metadata cleanup failed"}
    assert cleanup_calls == [target / ".git", target]


def test_install_rejects_source_before_git_and_sanitizes_clone_failure(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(
        install,
        "resolve_git_source_url",
        lambda _url: (
            None,
            "git source scheme not allowed (only http/https)",
        ),
    )
    monkeypatch.setattr(
        install.subprocess,
        "run",
        lambda *_a, **_k: pytest.fail("rejected source reached git"),
    )
    rejected = install.install_skill("bad", "ext::echo secret", skills_dir=tmp_path)
    assert rejected == {
        "ok": False,
        "error": "git source scheme not allowed (only http/https)",
    }

    source_url = "https://example.com/repository"
    monkeypatch.setattr(
        install,
        "resolve_git_source_url",
        lambda url: (_resolved_source(url), None),
    )
    monkeypatch.setattr(install.shutil, "which", lambda name: "/usr/bin/git")

    def fail_clone(*_args, **_kwargs):
        target = tmp_path / "third_party" / "failed"
        target.mkdir(parents=True)
        (target / "partial").write_text("partial", encoding="utf-8")
        return SimpleNamespace(returncode=128)

    monkeypatch.setattr(install.subprocess, "run", fail_clone)
    failed = install.install_skill("failed", source_url, skills_dir=tmp_path)
    assert failed == {"ok": False, "error": "git clone failed", "exit_code": 128}
    assert source_url not in str(failed)
    assert not (tmp_path / "third_party" / "failed").exists()


def test_install_fails_closed_on_inconsistent_resolution(tmp_path, monkeypatch):
    monkeypatch.setattr(
        install, "resolve_git_source_url", lambda _url: (None, None)
    )
    monkeypatch.setattr(
        install.subprocess,
        "run",
        lambda *_a, **_k: pytest.fail("inconsistent resolution reached git"),
    )
    result = install.install_skill(
        "inconsistent", "https://example.com/repository", skills_dir=tmp_path
    )
    assert result == {
        "ok": False,
        "error": "git source resolution failed closed",
    }


def test_install_handles_missing_git_and_clone_timeout(tmp_path, monkeypatch):
    monkeypatch.setattr(
        install,
        "resolve_git_source_url",
        lambda url: (_resolved_source(url), None),
    )
    monkeypatch.setattr(install.shutil, "which", lambda _name: None)
    missing = install.install_skill(
        "missing", "https://example.com/repository", skills_dir=tmp_path
    )
    assert missing == {"ok": False, "error": "git executable not found"}

    monkeypatch.setattr(install.shutil, "which", lambda _name: "/usr/bin/git")

    def timeout_clone(*_args, **_kwargs):
        target = tmp_path / "third_party" / "timeout"
        target.mkdir(parents=True)
        (target / "partial").write_text("partial", encoding="utf-8")
        raise install.subprocess.TimeoutExpired(["git", "clone"], 60)

    monkeypatch.setattr(install.subprocess, "run", timeout_clone)
    timed_out = install.install_skill(
        "timeout", "https://example.com/repository", skills_dir=tmp_path
    )
    assert timed_out == {"ok": False, "error": "git clone timed out"}
    assert not (tmp_path / "third_party" / "timeout").exists()
