"""T64: Git skill sources must not inherit executable Git transports."""
from __future__ import annotations

import os
from types import SimpleNamespace

import pytest

import arena.skills.git_source as policy
import arena.skills.install as install


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
def test_non_http_git_transports_are_rejected_without_resolution(monkeypatch, url):
    monkeypatch.setattr(
        policy,
        "_validate_url",
        lambda _url: pytest.fail("rejected schemes must not resolve"),
    )
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
def test_credentials_are_rejected_before_ssrf_check(monkeypatch, url):
    monkeypatch.setattr(
        policy,
        "_validate_url",
        lambda _url: pytest.fail("credential-bearing URLs must not resolve"),
    )
    assert policy.validate_git_source_url(url) == (
        "credentials in git source URL are not allowed"
    )


def test_missing_host_invalid_port_and_ssrf_error_are_structured(monkeypatch):
    assert policy.validate_git_source_url("https:///repository") == (
        "git source host is required"
    )
    assert policy.validate_git_source_url("https://example.com:0/repository") == (
        "git source port is invalid"
    )
    assert policy.validate_git_source_url("https://example.com:99999/repository") == (
        "invalid git source URL"
    )
    monkeypatch.setattr(
        policy,
        "_validate_url",
        lambda _url: "host resolves to a private/internal address",
    )
    assert policy.validate_git_source_url("https://internal.test/repository") == (
        "git source rejected: host resolves to a private/internal address"
    )


def test_public_http_and_https_sources_are_accepted(monkeypatch):
    seen = []
    monkeypatch.setattr(
        policy,
        "_validate_url",
        lambda url: seen.append(url) or None,
    )
    assert policy.validate_git_source_url("https://example.com/repository") is None
    assert policy.validate_git_source_url("http://example.com:8080/repository") is None
    assert policy.validate_git_source_url("https://example.com:1/repository") is None
    assert seen == [
        "https://example.com/repository",
        "http://example.com:8080/repository",
        "https://example.com:1/repository",
    ]


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
    })
    assert result == {
        "PATH": "bin",
        "GIT_ALLOW_PROTOCOL": "https:http",
        "GIT_PROTOCOL_FROM_USER": "0",
        "GIT_SSH_COMMAND": "ssh-custom",
    }


def test_install_git_source_uses_exact_transport_environment(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(install, "validate_git_source_url", lambda _url: None)
    monkeypatch.setattr(
        install,
        "git_protocol_environment",
        lambda environ: {"SAFE": str(environ is os.environ)},
    )

    def run(argv, **kwargs):
        calls.append((argv, kwargs))
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(install.subprocess, "run", run)
    result = install.install_skill(
        "demo", "https://example.com/demo", skills_dir=tmp_path
    )
    target = tmp_path / "third_party" / "demo"
    assert result == {"ok": True, "path": str(target), "name": "demo"}
    assert calls == [
        (["git", "clone", "--depth", "1", "--", "https://example.com/demo", str(target)], {
            "check": False,
            "capture_output": True,
            "env": {"SAFE": "True"},
        })
    ]


def test_install_rejects_source_before_git_and_sanitizes_clone_failure(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(
        install,
        "validate_git_source_url",
        lambda _url: "git source scheme not allowed (only http/https)",
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

    secret_url = "https://example.com/repository"
    monkeypatch.setattr(install, "validate_git_source_url", lambda _url: None)
    monkeypatch.setattr(
        install.subprocess,
        "run",
        lambda *_a, **_k: SimpleNamespace(returncode=128),
    )
    failed = install.install_skill("failed", secret_url, skills_dir=tmp_path)
    assert failed == {"ok": False, "error": "git clone failed", "exit_code": 128}
    assert secret_url not in str(failed)
    assert not (tmp_path / "third_party" / "failed").exists()
