"""Tests for arena/agentctl_cli/tls.py -- the v4.41.0 shared
TLS context helper (audit finding #2).

Behaviour matrix under test:

* http:// URL              -> None regardless of env
* https:// URL, env unset  -> strict verify context
* https:// URL, env truthy -> insecure context + WARN once
* env truthy but URL http  -> still None (no warning)
* warn-once semantics      -> multiple calls, one warning
* reset_warning_guard_for_tests works
"""
from __future__ import annotations

import ssl

import pytest

from arena.agentctl_cli import tls as tls_mod


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    """Every test starts with the insecure flag unset and the
    warning guard cleared. Otherwise test ordering could hide
    real regressions -- e.g. a test running after another that
    already tripped the warning would silently pass a
    "warning shown" assertion."""
    monkeypatch.delenv("ARENA_INSECURE_TLS", raising=False)
    tls_mod.reset_warning_guard_for_tests()
    yield
    tls_mod.reset_warning_guard_for_tests()


# ---------------------------------------------------------------------------
# is_insecure_tls_enabled -- env resolution
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("val,expected", [
    ("1", True), ("true", True), ("TRUE", True),
    ("yes", True), ("YES", True), ("on", True), ("On", True),
    ("0", False), ("false", False), ("no", False), ("off", False),
    ("", False), ("please", False), ("2", False),
])
def test_is_insecure_tls_env_shapes(monkeypatch, val, expected):
    """Only the four commonly-typed truthy values enable
    insecure mode. A mistyped 'please' must not silently
    downgrade security."""
    monkeypatch.setenv("ARENA_INSECURE_TLS", val)
    assert tls_mod.is_insecure_tls_enabled() is expected


def test_is_insecure_tls_unset_is_secure(monkeypatch):
    monkeypatch.delenv("ARENA_INSECURE_TLS", raising=False)
    assert tls_mod.is_insecure_tls_enabled() is False


# ---------------------------------------------------------------------------
# build_ssl_context -- scheme + env matrix
# ---------------------------------------------------------------------------
def test_http_url_returns_none_regardless_of_env(monkeypatch):
    """Plain HTTP never enters the TLS path; passing a context
    to urllib on http is a latent bug we don't want to trigger."""
    monkeypatch.setenv("ARENA_INSECURE_TLS", "1")
    assert tls_mod.build_ssl_context("http://foo/bar") is None
    monkeypatch.delenv("ARENA_INSECURE_TLS")
    assert tls_mod.build_ssl_context("http://foo/bar") is None


def test_https_default_is_strict_verify():
    """v4.41.0 default. Previously (pre-v4.41.0) this used to
    return an insecure context on every https URL. The whole
    point of this release is to flip that default."""
    ctx = tls_mod.build_ssl_context("https://example.com")
    assert ctx is not None
    assert ctx.check_hostname is True
    assert ctx.verify_mode == ssl.CERT_REQUIRED


def test_https_insecure_env_disables_verify(monkeypatch):
    monkeypatch.setenv("ARENA_INSECURE_TLS", "1")
    ctx = tls_mod.build_ssl_context("https://example.com")
    assert ctx is not None
    assert ctx.check_hostname is False
    assert ctx.verify_mode == ssl.CERT_NONE


# ---------------------------------------------------------------------------
# Warning-once behaviour
# ---------------------------------------------------------------------------
def test_insecure_mode_warns_once_on_stderr(monkeypatch, capsys):
    monkeypatch.setenv("ARENA_INSECURE_TLS", "1")
    # Three calls -- only one warning line expected.
    tls_mod.build_ssl_context("https://a.example")
    tls_mod.build_ssl_context("https://b.example")
    tls_mod.build_ssl_context("https://c.example")
    err = capsys.readouterr().err
    warning_lines = [line for line in err.splitlines()
                     if "TLS verification disabled" in line]
    assert len(warning_lines) == 1, (
        f"expected exactly one warning, got {len(warning_lines)}:\n{err}"
    )


def test_secure_mode_is_silent(monkeypatch, capsys):
    """No env, no warning -- silence is the entire point of the
    happy path."""
    monkeypatch.delenv("ARENA_INSECURE_TLS", raising=False)
    tls_mod.build_ssl_context("https://a.example")
    tls_mod.build_ssl_context("https://b.example")
    err = capsys.readouterr().err
    assert "TLS verification disabled" not in err


def test_http_url_in_insecure_mode_does_not_warn(monkeypatch, capsys):
    """Insecure env is set but we're calling on http -- no TLS
    was actually used, so no warning."""
    monkeypatch.setenv("ARENA_INSECURE_TLS", "1")
    tls_mod.build_ssl_context("http://loopback")
    err = capsys.readouterr().err
    assert "TLS verification disabled" not in err


def test_reset_warning_guard_lets_warning_fire_again(monkeypatch, capsys):
    monkeypatch.setenv("ARENA_INSECURE_TLS", "1")
    tls_mod.build_ssl_context("https://a.example")
    tls_mod.reset_warning_guard_for_tests()
    tls_mod.build_ssl_context("https://b.example")
    err = capsys.readouterr().err
    warning_lines = [line for line in err.splitlines()
                     if "TLS verification disabled" in line]
    assert len(warning_lines) == 2
