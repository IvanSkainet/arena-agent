"""Built-in TLS/HTTPS configuration helpers and handler."""
from __future__ import annotations

import shutil
import socket
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from aiohttp import web

from arena.constants import APP_DIR
from arena.handler_context import TlsHandlerContext
from arena.handler_helpers import authed, err_json

TLS_CONFIG: dict[str, Any] = {
    "enabled": False,
    "cert_path": "",
    "key_path": "",
    "auto_cert": False,       # Auto-generate self-signed cert
    "tailscale_cert": False,  # Use Tailscale cert
}


@dataclass(frozen=True)
class TlsHandlers:
    tls: object


def generate_self_signed_cert(*, log_info: Any = None, log_warning: Any = None) -> tuple[str, str]:
    """Generate a self-signed TLS certificate for local development.

    Returns (cert_path, key_path).
    Uses openssl if available, otherwise creates a simple cert via Python's ssl module.
    """
    cert_dir = APP_DIR / "tls"
    cert_dir.mkdir(parents=True, exist_ok=True)
    cert_path = str(cert_dir / "bridge.crt")
    key_path = str(cert_dir / "bridge.key")

    # Try openssl first (most reliable).
    if shutil.which("openssl"):
        try:
            subprocess.run([
                "openssl", "req", "-x509", "-newkey", "rsa:2048",
                "-keyout", key_path, "-out", cert_path,
                "-days", "365", "-nodes",
                "-subj", "/CN=arena-bridge/O=Arena/C=US",
            ], capture_output=True, timeout=30, check=True)
            if log_info:
                log_info("[TLS] Generated self-signed certificate via openssl")
            return cert_path, key_path
        except Exception as e:
            if log_warning:
                log_warning("[TLS] openssl cert generation failed: %s", e)

    # Fallback: use Python cryptography if available.
    try:
        from cryptography import x509
        from cryptography.x509.oid import NameOID
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import rsa

        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        subject = issuer = x509.Name([
            x509.NameAttribute(NameOID.COMMON_NAME, "arena-bridge"),
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Arena"),
        ])
        cert = (x509.CertificateBuilder()
                .subject_name(subject)
                .issuer_name(issuer)
                .public_key(key.public_key())
                .serial_number(x509.random_serial_number())
                .not_valid_before(datetime.now(timezone.utc))
                .not_valid_after(datetime.now(timezone.utc) + __import__("datetime").timedelta(days=365))
                .sign(key, hashes.SHA256()))

        with open(key_path, "wb") as f:
            f.write(key.private_bytes(serialization.Encoding.PEM,
                                      serialization.PrivateFormat.TraditionalOpenSSL,
                                      serialization.NoEncryption()))
        with open(cert_path, "wb") as f:
            f.write(cert.public_bytes(serialization.Encoding.PEM))

        if log_info:
            log_info("[TLS] Generated self-signed certificate via Python cryptography")
        return cert_path, key_path
    except ImportError:
        pass
    except Exception as e:
        if log_warning:
            log_warning("[TLS] Python cert generation failed: %s", e)

    return "", ""


def get_tailscale_cert(*, log_info: Any = None) -> tuple[str, str]:
    """Try to get Tailscale certificate for the current machine.

    Tailscale stores certs in /var/lib/tailscale/certs/ or ~/.ts/certs/.
    """
    hostname = socket.gethostname()
    cert_dirs = [
        Path("/var/lib/tailscale/certs"),
        Path.home() / ".ts" / "certs",
    ]

    for cert_dir in cert_dirs:
        cert_path = cert_dir / f"{hostname}.crt"
        key_path = cert_dir / f"{hostname}.key"
        if cert_path.exists() and key_path.exists():
            if log_info:
                log_info("[TLS] Found Tailscale certificate at %s", cert_dir)
            return str(cert_path), str(key_path)

    return "", ""


def make_tls_handlers(ctx: TlsHandlerContext) -> TlsHandlers:
    @authed(ctx)
    async def handle_v1_tls(request: web.Request) -> web.Response:
        """GET /v1/tls — TLS configuration status.
        POST /v1/tls — Configure TLS (enable/disable, set cert paths, auto-cert).
        """

        if request.method == "POST":
            try:
                data = await request.json()
                if "enabled" in data:
                    TLS_CONFIG["enabled"] = bool(data["enabled"])
                if "cert_path" in data:
                    TLS_CONFIG["cert_path"] = str(data["cert_path"])
                if "key_path" in data:
                    TLS_CONFIG["key_path"] = str(data["key_path"])
                if "auto_cert" in data:
                    TLS_CONFIG["auto_cert"] = bool(data["auto_cert"])
                if "tailscale_cert" in data:
                    TLS_CONFIG["tailscale_cert"] = bool(data["tailscale_cert"])

                # Auto-generate cert if requested.
                if TLS_CONFIG["auto_cert"] and not TLS_CONFIG["cert_path"]:
                    cert, key = ctx.generate_self_signed_cert()
                    if cert and key:
                        TLS_CONFIG["cert_path"] = cert
                        TLS_CONFIG["key_path"] = key
                        TLS_CONFIG["enabled"] = True

                # Try Tailscale cert if requested.
                if TLS_CONFIG["tailscale_cert"] and not TLS_CONFIG["cert_path"]:
                    cert, key = ctx.get_tailscale_cert()
                    if cert and key:
                        TLS_CONFIG["cert_path"] = cert
                        TLS_CONFIG["key_path"] = key
                        TLS_CONFIG["enabled"] = True

                ctx.log_info("[TLS] Configuration updated: enabled=%s, cert=%s",
                             TLS_CONFIG["enabled"], TLS_CONFIG["cert_path"])
            except Exception as e:
                return ctx.cors_json_response({"ok": False, "error": str(e)}, status=400)

        # Verify cert files exist.
        cert_exists = Path(TLS_CONFIG["cert_path"]).exists() if TLS_CONFIG["cert_path"] else False
        key_exists = Path(TLS_CONFIG["key_path"]).exists() if TLS_CONFIG["key_path"] else False

        return ctx.cors_json_response({
            "ok": True,
            "tls": {
                "enabled": TLS_CONFIG["enabled"],
                "cert_path": TLS_CONFIG["cert_path"],
                "key_path": TLS_CONFIG["key_path"],
                "auto_cert": TLS_CONFIG["auto_cert"],
                "tailscale_cert": TLS_CONFIG["tailscale_cert"],
                "cert_exists": cert_exists,
                "key_exists": key_exists,
                "ready": TLS_CONFIG["enabled"] and cert_exists and key_exists,
            }
        })

    return TlsHandlers(tls=handle_v1_tls)
