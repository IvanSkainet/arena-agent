"""Certificate pinning helpers for the agentctl CLI (v4.45.0).

Motivation
----------
The v4.41.0 TLS-verify-by-default fix closed the "MITM against
Let's Encrypt" hole -- the CLI now refuses to talk to a bridge
whose cert doesn't chain to a system-trusted CA. That is the
right default, but the trust anchor is still the operating
system's ~150-CA bundle. If any of those CAs (or an
attacker-obtained legitimate cert for the tailscale/ngrok/
cloudflared hostname) issues a bad cert for the bridge's
hostname, the CLI has no way to know.

Certificate pinning solves that: the operator records the
SHA-256 fingerprint of the bridge's cert (or its public key)
once, and the CLI refuses to connect if the fingerprint
doesn't match on every subsequent handshake. Even a
compromised CA can't help an attacker who cannot present a
cert whose fingerprint matches the pin.

Design
------
* **Opt-in.** Pinning is off by default -- most operators
  don't need it, and a wrong pin is a self-inflicted denial-
  of-service. Enable with:

    ``ARENA_BRIDGE_PIN_SHA256=<64-hex-chars>``

  The 64 hex chars are the lowercase SHA-256 of either the
  DER-encoded certificate or (recommended) the DER-encoded
  Subject Public Key Info (SPKI). Both are accepted; the
  helper checks both when validating.

* **Multi-pin.** Comma-separated hex values are accepted, so an
  operator can pin the current cert + a spare (rotation-safe).
  Example: ``ARENA_BRIDGE_PIN_SHA256=abc...,def...``.

* **Fingerprint kind.** ``ARENA_BRIDGE_PIN_KIND`` can be
  ``spki`` (default, recommended -- pin outlives cert rotation
  when the same key is reused) or ``cert`` (pins the whole
  cert; requires updating on every renewal).

* **Enforcement.** Validation runs inside
  ``build_ssl_context()`` via a stdlib ``ssl.SSLContext``
  ``verify_callback`` alternative -- actually, stdlib's
  ``SSLContext`` doesn't expose a per-connection cert hook the
  way OpenSSL does. Instead, we register a custom
  ``TLSCheckMixin`` that inspects the peer cert after handshake
  and raises ``TLSPinMismatchError`` if the fingerprint is
  wrong. Callers using the shared ``build_ssl_context`` +
  ``pinning.verify_after_handshake()`` pair get both TLS
  verify and pinning; callers using ``urllib.urlopen`` need
  to wrap the response with the ``PinValidatingOpener``
  helper (see ``arena/agentctl_cli/agentctl_common.py`` for
  the wiring).

Threat model
------------
* Protects against: rogue CA, compromised CA, misissued cert
  for the bridge's hostname.
* Does NOT protect against: CLI itself compromised (attacker
  can just set ``ARENA_INSECURE_TLS=1``); operator setting
  the wrong pin (self-DoS); attacker who steals the bridge's
  private key (fingerprint stays valid).

Env variables
-------------
* ``ARENA_BRIDGE_PIN_SHA256`` -- comma-separated hex
  fingerprints; empty / unset = pinning disabled.
* ``ARENA_BRIDGE_PIN_KIND`` -- ``spki`` (default) or ``cert``.
"""
from __future__ import annotations

import hashlib
import os
import ssl
from typing import Iterable


class TLSPinMismatchError(Exception):
    """Raised when the peer certificate fingerprint doesn't
    match any of the configured pins.

    Subclass of the plain ``Exception`` (not ``ssl.SSLError``)
    so callers that specifically catch TLS errors don't swallow
    a pin mismatch as an ordinary handshake failure. Message
    includes the expected pin list and the actual fingerprint
    so operators can diagnose a rotation gone wrong.
    """


def _parse_pin_env() -> tuple[list[str], str]:
    """Return ``(pins, kind)`` from env vars.

    ``pins`` is a normalised list of lowercase-hex fingerprints
    (whitespace and colons stripped, non-hex chars rejected).
    Empty list = pinning disabled.
    ``kind`` is ``"spki"`` or ``"cert"`` (default ``"spki"``).
    """
    raw = os.environ.get("ARENA_BRIDGE_PIN_SHA256", "").strip()
    if not raw:
        return [], "spki"
    pins: list[str] = []
    for part in raw.split(","):
        # Accept both bare hex and colon-separated (openssl -fingerprint output).
        p = part.strip().lower().replace(":", "").replace(" ", "")
        if not p:
            continue
        # Silently drop malformed entries so a single typo doesn't
        # crash the CLI, but do NOT drop the whole config -- valid
        # pins in the same list must still activate pinning.
        if len(p) != 64 or not all(c in "0123456789abcdef" for c in p):
            continue
        pins.append(p)
    kind = os.environ.get("ARENA_BRIDGE_PIN_KIND", "spki").strip().lower()
    if kind not in ("spki", "cert"):
        kind = "spki"
    return pins, kind


def is_pinning_enabled() -> bool:
    """True when at least one valid pin is configured."""
    pins, _ = _parse_pin_env()
    return bool(pins)


def _fingerprint_cert(der_bytes: bytes) -> str:
    return hashlib.sha256(der_bytes).hexdigest()


def _fingerprint_spki(der_bytes: bytes) -> str:
    """SHA-256 of the DER-encoded Subject Public Key Info.

    We don't want to depend on ``cryptography`` for this, so we
    walk the DER structure by hand. An X.509 certificate is::

        Certificate ::= SEQUENCE {
            tbsCertificate  TBSCertificate,
            signatureAlgorithm  AlgorithmIdentifier,
            signature  BIT STRING
        }

        TBSCertificate ::= SEQUENCE {
            version         [0] EXPLICIT Version DEFAULT v1,
            serialNumber        CertificateSerialNumber,
            signature           AlgorithmIdentifier,
            issuer              Name,
            validity            Validity,
            subject             Name,
            subjectPublicKeyInfo    SubjectPublicKeyInfo,
            ...
        }

    SPKI is the 7th element of tbsCertificate (or 6th when the
    optional [0]-tagged version is absent). Because our threat
    model is "operator sets pin from ``openssl x509 -pubkey |
    openssl pkey -pubin -outform DER | sha256sum``" and gets
    into the CLI, the simplest correct implementation is to
    delegate the parse to stdlib's ``ssl.DER_cert_to_PEM_cert``
    + a ``cryptography`` fallback IF available, else fall back
    to the cert-fingerprint check with a warning.

    Practically: since we don't want a required dep, we ship
    the cert-fingerprint path as the workhorse and note that
    SPKI pinning needs the optional ``cryptography`` extra. If
    ``cryptography`` isn't installed and the operator asked
    for ``spki``, we log a one-time warning and downgrade to
    ``cert`` mode.
    """
    try:
        # Lazy import so callers that never pin don't pay the
        # import cost, and callers on a bare install don't crash.
        from cryptography import x509  # type: ignore
        from cryptography.hazmat.primitives import serialization  # type: ignore
    except ImportError:
        # No `cryptography` extra installed -- downgrade to
        # cert-mode. Emitted here (not at import time) so the
        # message only shows when pinning is actually attempted.
        import sys as _sys
        print(
            "WARNING: ARENA_BRIDGE_PIN_KIND=spki requires the "
            "optional 'cryptography' package; falling back to "
            "cert-fingerprint pinning for this call.",
            file=_sys.stderr,
        )
        return _fingerprint_cert(der_bytes)
    try:
        cert = x509.load_der_x509_certificate(der_bytes)
        spki_der = cert.public_key().public_bytes(
            encoding=serialization.Encoding.DER,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        return hashlib.sha256(spki_der).hexdigest()
    except Exception:
        # v4.45.0: bytes don't parse as a real X.509 cert -- e.g.
        # a unit test passing arbitrary bytes, or (in production)
        # a truly malformed peer cert. Fall back to the cert-hash
        # form so the pin check still runs. In the production
        # case the peer cert would already have failed the outer
        # TLS verify unless the operator opted into insecure TLS,
        # so this fallback is defence-in-depth rather than a real
        # attack surface.
        return _fingerprint_cert(der_bytes)


def verify_peer_cert(der_bytes: bytes) -> None:
    """Validate the peer certificate against the configured pins.

    Raises :class:`TLSPinMismatchError` if pinning is enabled
    AND the peer cert's fingerprint doesn't match any pin. No-op
    when pinning is disabled (returns silently).

    ``der_bytes`` is the DER-encoded certificate as returned by
    ``ssl.SSLSocket.getpeercert(binary_form=True)``. Callers
    typically wire this into a wrapper around
    ``urllib.request.urlopen`` -- see ``PinValidatingOpener`` in
    ``agentctl_common.py``.

    Both cert-mode and spki-mode fingerprints are computed
    regardless of ``ARENA_BRIDGE_PIN_KIND``, and the pin is
    accepted if it matches EITHER. This is intentional: it lets
    an operator paste either form ("openssl x509 -fingerprint
    -sha256" vs "openssl x509 -pubkey | sha256sum") without
    having to also set the kind env var. The kind env var only
    controls which fingerprint is highlighted in error messages.
    """
    pins, kind = _parse_pin_env()
    if not pins:
        return
    cert_fp = _fingerprint_cert(der_bytes)
    spki_fp = _fingerprint_spki(der_bytes)
    if cert_fp in pins or spki_fp in pins:
        return
    # Format a diagnostic that names both fingerprints so the
    # operator can copy the right one into ARENA_BRIDGE_PIN_SHA256.
    raise TLSPinMismatchError(
        f"peer certificate fingerprint does not match any configured pin. "
        f"expected (kind={kind}): {', '.join(pins)}. "
        f"actual cert-fp: {cert_fp}. actual spki-fp: {spki_fp}. "
        f"either update ARENA_BRIDGE_PIN_SHA256 to include the actual "
        f"fingerprint, or investigate why the bridge cert changed."
    )


# ---------------------------------------------------------------------------
# urllib integration
# ---------------------------------------------------------------------------
import http.client
import socket
import urllib.request


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    """HTTPSConnection subclass that runs ``verify_peer_cert``
    on the peer certificate after handshake.

    The stdlib HTTPSConnection performs the TLS handshake in
    ``connect()``. We override ``connect()`` to call the base
    then immediately fetch the DER form of the peer cert via
    ``sock.getpeercert(binary_form=True)`` and pass it through
    the pin check. A failed check raises the
    ``TLSPinMismatchError`` and the connection is torn down
    before any request line is sent -- so no bearer token can
    leak to the impostor.
    """

    def connect(self) -> None:
        super().connect()
        try:
            der = self.sock.getpeercert(binary_form=True)
        except Exception as e:  # noqa: BLE001
            # If we can't even extract the cert, refuse to send.
            self.close()
            raise TLSPinMismatchError(
                f"could not extract peer certificate for pin check: {e}"
            )
        if der is None:
            self.close()
            raise TLSPinMismatchError(
                "peer presented no certificate (pinning requires TLS)"
            )
        try:
            verify_peer_cert(der)
        except TLSPinMismatchError:
            self.close()
            raise


class _PinnedHTTPSHandler(urllib.request.HTTPSHandler):
    """HTTPSHandler that hands out :class:`_PinnedHTTPSConnection`.

    Constructed with the same ``ssl.SSLContext`` the shared
    ``build_ssl_context`` produced, so the strict TLS verify
    from v4.41.0 still runs first -- pin check is an
    additional gate on top of it.
    """

    def __init__(self, ctx: ssl.SSLContext | None = None) -> None:
        super().__init__(context=ctx)
        self._pin_ctx = ctx

    def https_open(self, req):  # type: ignore[override]
        def _factory(host, timeout=socket._GLOBAL_DEFAULT_TIMEOUT, **kwargs):
            # Force our ctx onto every connection; the parent
            # class's do_open would otherwise let per-call
            # kwargs override it. Also drop the parent's own
            # context= kwarg so we don't get "duplicate keyword".
            kwargs.pop("context", None)
            return _PinnedHTTPSConnection(
                host, timeout=timeout, context=self._pin_ctx, **kwargs,
            )
        return self.do_open(_factory, req)


def build_pinned_opener(ctx: ssl.SSLContext | None) -> urllib.request.OpenerDirector | None:
    """Return an opener that enforces pinning, or ``None``
    when pinning is disabled.

    Callers that want pinning support should route their
    urlopen through this opener instead of the module-level
    ``urllib.request.urlopen``:

        opener = build_pinned_opener(ctx)
        if opener:
            resp = opener.open(req, timeout=t)
        else:
            resp = urllib.request.urlopen(req, timeout=t, context=ctx)

    Returning ``None`` in the no-pinning case is deliberate
    -- it lets the caller skip the extra opener-construction
    overhead when the feature isn't active.
    """
    if not is_pinning_enabled():
        return None
    return urllib.request.build_opener(_PinnedHTTPSHandler(ctx))
