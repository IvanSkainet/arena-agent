"""Benchmarks for the SSRF validator.

``arena.security_ssrf._validate_url`` guards every browser/fetch endpoint,
so it runs before any outbound request the bridge is asked to make. Most
of its cost is regex-driven address spelling analysis: ``_coerce_ip``
tries four different ways to read a host as an address (dotted quad,
hexadecimal, octal, ``inet_aton`` short form) before the validator is
willing to call it a hostname.

Every URL below is chosen to return *before* the final
``socket.getaddrinfo`` fallback. A benchmark that reached the resolver
would be measuring the network, not the validator, and would be neither
deterministic nor meaningful.
"""
from __future__ import annotations

from arena.security_ssrf import (
    _coerce_ip,
    _components_fit_ipv4,
    _looks_numeric_host,
    _validate_url,
)

# All refused, all without a DNS lookup: blocked hostname, loopback,
# private ranges, link-local metadata, IPv4-mapped IPv6, and the numeric
# spellings (hex / octal / integer / short form) that exist to smuggle one
# of the above past a naive check.
BLOCKED_URLS = [
    "http://localhost:8765/v1/exec",
    "http://127.0.0.1/admin",
    "https://10.0.0.7/internal/metrics",
    "http://192.168.1.1/router",
    "http://169.254.169.254/latest/meta-data/iam/security-credentials/",
    "http://metadata.google.internal/computeMetadata/v1/",
    "http://[::1]:9000/",
    "http://[::ffff:127.0.0.1]/",
    "http://2130706433/",
    "http://0x7f000001/",
    "http://017700000001/",
    "http://127.1/",
    "http://internal.service.local/health",
    "ftp://example.com/payload.bin",
    "file:///etc/passwd",
]

# Refused for shape rather than for reachability: an all-numeric host that
# no spelling can turn into an in-range address.
MALFORMED_URLS = [
    "http://99999999999999/",
    "http://256.256.256.256/",
    "http://0x100000000/",
]

HOST_SPELLINGS = [
    "127.0.0.1", "10.0.0.7", "2130706433", "0x7f000001", "017700000001",
    "127.1", "::1", "::ffff:169.254.169.254", "example.com", "1.2.3.4.5",
]


def test_validate_url_blocked_batch(benchmark) -> None:
    """The refusal path over every blocked spelling we know about."""

    def validate_all() -> int:
        return sum(1 for url in BLOCKED_URLS if _validate_url(url) is not None)

    assert benchmark(validate_all) == len(BLOCKED_URLS)


def test_validate_url_malformed_numeric_batch(benchmark) -> None:
    """Out-of-range numeric hosts: the full ``_coerce_ip`` miss path."""

    def validate_all() -> int:
        return sum(1 for url in MALFORMED_URLS if _validate_url(url) is not None)

    assert benchmark(validate_all) == len(MALFORMED_URLS)


def test_coerce_ip_host_spellings(benchmark) -> None:
    """Address coercion alone, without the URL parse around it."""

    def coerce_all() -> int:
        return sum(1 for host in HOST_SPELLINGS if _coerce_ip(host) is not None)

    assert benchmark(coerce_all) == 8


def test_looks_numeric_host(benchmark) -> None:
    """The all-numeric check: one regex per dotted component."""

    def check_all() -> int:
        return sum(1 for host in HOST_SPELLINGS if _looks_numeric_host(host))

    assert benchmark(check_all) >= 1


def test_components_fit_ipv4(benchmark) -> None:
    """Per-component range checking, including the mixed-radix forms."""
    cases = [
        ["127", "0", "0", "1"],
        ["0x7f", "0", "0", "1"],
        ["017", "1"],
        ["2130706433"],
        ["300", "1", "1", "1"],
    ]

    def check_all() -> int:
        return sum(1 for parts in cases if _components_fit_ipv4(parts))

    assert benchmark(check_all) == 4
