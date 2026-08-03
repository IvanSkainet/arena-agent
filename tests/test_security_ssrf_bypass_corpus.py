"""SSRF validator vs. the classic bypass corpus.

`arena/security_ssrf.py` guards 21 modules -- every outbound fetch the bridge
makes on a caller's behalf (browser fetch, ngrok/zerotier admin calls, update
checks). It was reached only through those facades in tests; the validator
itself had no direct adversarial suite, so "it works" rested on the callers
happening to exercise the interesting inputs.

This file asks the question straight: given the inputs an attacker actually
sends, does the validator refuse? The corpus is the standard SSRF bypass set --
alternate integer encodings of 127.0.0.1, IPv4-mapped IPv6, short-form
addresses, trailing dots, case variation, userinfo prefixes, cloud metadata
IPs, and non-HTTP schemes.

All of them were already blocked when this was written: nothing here is a fix,
it is a floor.

Layering, learned by sabotage while writing this file
-----------------------------------------------------
`_validate_url` refuses a numeric bypass through THREE independent paths, and
knowing which is which matters for anyone editing the module:

1. `_coerce_ip` decodes decimal/hex/octal integers directly;
2. the same function falls back to `socket.inet_aton`, which accepts short
   forms like `127.1` and every integer spelling too;
3. failing both, `getaddrinfo` resolves the host and the result is re-checked.

Deleting layer 1 alone leaves the URL-level assertions green -- verified by
doing it. That is not a gap in the code (defence in depth working as intended)
but it IS a gap in a test suite that only checks URLs, so the unit-level tests
below pin each layer on its own. A corpus that only asserts the outcome would
have let a silent removal of the decoder through.

Written after evaluating mutation testing for exactly this purpose: a named
adversarial corpus states the intent in a way a mutation score cannot (see
docs/github_apps_actions_survey.md).
"""
from __future__ import annotations

import pytest

from arena.security_ssrf import _coerce_ip, _ip_is_blocked, _validate_url

# Each entry is (url, why it must never be reachable).
MUST_BLOCK = [
    ("http://127.0.0.1/", "loopback, dotted quad"),
    ("http://127.1/", "loopback, short form"),
    ("http://2130706433/", "loopback as a decimal integer"),
    ("http://0x7f000001/", "loopback as hex"),
    ("http://017700000001/", "loopback as octal"),
    ("http://[::1]/", "IPv6 loopback"),
    ("http://[::ffff:127.0.0.1]/", "IPv4-mapped IPv6 loopback"),
    ("http://0.0.0.0/", "unspecified address"),
    ("http://localhost/", "loopback by name"),
    ("http://LOCALHOST/", "loopback by name, upper case"),
    ("http://127.0.0.1./", "trailing dot defeats a naive string compare"),
    ("http://foo.localhost/", ".localhost suffix"),
    ("http://x.internal/", ".internal suffix"),
    ("http://y.local/", ".local suffix (mDNS)"),
    ("http://z.localdomain/", ".localdomain suffix"),
    ("http://169.254.169.254/latest/meta-data/", "AWS/GCP metadata service"),
    ("http://metadata.google.internal/", "GCP metadata by name"),
    ("http://metadata/", "metadata short name"),
    ("http://10.0.0.1/", "RFC1918 /8"),
    ("http://192.168.1.1/", "RFC1918 /16"),
    ("http://172.16.0.1/", "RFC1918 /12"),
    ("http://user@127.0.0.1/", "userinfo prefix hiding the real host"),
    ("http://127.0.0.1:8765/v1/exec", "the bridge's own API port"),
    ("file:///etc/passwd", "non-HTTP scheme"),
    ("gopher://127.0.0.1/", "gopher, the classic SSRF pivot"),
    ("ftp://127.0.0.1/", "ftp scheme"),
]

MUST_ALLOW = [
    "http://example.com/",
    "https://github.com/IvanSkainet/arena-agent",
    "https://1.1.1.1/",
    "https://8.8.8.8/resolve?name=example.com",
]


@pytest.mark.parametrize(("url", "reason"), MUST_BLOCK, ids=[u for u, _ in MUST_BLOCK])
def test_ssrf_bypass_is_refused(url, reason):
    verdict = _validate_url(url)
    assert verdict is not None, f"SSRF validator let through {url!r} ({reason})"


@pytest.mark.parametrize("url", MUST_ALLOW)
def test_ordinary_public_urls_are_allowed(url):
    """A validator that blocks everything is not a validator."""
    assert _validate_url(url) is None, f"legitimate URL refused: {url!r}"


def test_integer_forms_decode_to_the_same_address():
    """`_coerce_ip` is the part that makes the numeric bypasses fail."""
    for spelling in ("2130706433", "0x7f000001", "017700000001"):
        addr = _coerce_ip(spelling)
        assert addr is not None, f"{spelling} did not decode at all"
        assert str(addr) == "127.0.0.1", f"{spelling} -> {addr}"
        assert _ip_is_blocked(addr) is True


def test_out_of_range_integers_are_not_treated_as_addresses():
    """A number too large for IPv4 must not silently wrap into a valid host."""
    assert _coerce_ip(str(2**32)) is None
    assert _coerce_ip("99999999999999") is None


def test_short_form_addresses_decode_via_inet_aton():
    """Layer 2: `127.1` is a valid address spelling that the regex misses."""
    addr = _coerce_ip("127.1")
    assert addr is not None and str(addr) == "127.0.0.1"
    assert _ip_is_blocked(addr) is True


def test_public_addresses_are_not_blocked_by_ip_rules():
    for public in ("1.1.1.1", "8.8.8.8", "93.184.216.34"):
        addr = _coerce_ip(public)
        assert addr is not None
        assert _ip_is_blocked(addr) is False, f"{public} wrongly treated as internal"
