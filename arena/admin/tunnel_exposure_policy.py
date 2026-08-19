"""Authorization policy for agent-requested public tunnel exposure."""
from __future__ import annotations

import hmac
from typing import Any

PUBLIC_TUNNEL_ACK = "I_ACCEPT_PUBLIC_BRIDGE_EXPOSURE"
PUBLIC_TUNNEL_PROVIDERS = frozenset({"tailscale", "cloudflared", "ngrok", "bore"})
PUBLIC_TUNNEL_ACK_HEADER = "X-Arena-Public-Exposure-Ack"


def public_start_denial(
    *,
    provider: str,
    action: str,
    ack: Any,
    authorization_source: str = "api",
) -> dict[str, Any] | None:
    """Return a structured denial when an API start lacks exact acknowledgement.

    Persisted operator configuration is a deliberate authorization source and
    remains restart-safe. Agent/API requests must carry the exact phrase.
    """
    normalized_provider = provider.strip().lower()
    normalized_action = action.strip().lower()
    is_public_request = (
        normalized_provider == "auto"
        or normalized_provider in PUBLIC_TUNNEL_PROVIDERS
    )
    if normalized_action != "start" or not is_public_request:
        return None
    if authorization_source == "operator_persisted":
        return None
    if (
        isinstance(ack, str)
        and len(ack) == len(PUBLIC_TUNNEL_ACK)
        and hmac.compare_digest(ack, PUBLIC_TUNNEL_ACK)
    ):
        return None
    return {
        "ok": False,
        "error": "tunnel_public_ack_required",
        "provider": normalized_provider,
        "required_ack": PUBLIC_TUNNEL_ACK,
        "ack_header": PUBLIC_TUNNEL_ACK_HEADER,
        "authorization_source": authorization_source,
        "message": (
            "Starting this provider can publish the Bridge to the public "
            "internet, protected only by its bearer token."
        ),
    }
