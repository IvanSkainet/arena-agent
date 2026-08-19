"""T69: agent-requested public exposure requires exact acknowledgement."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest
from aiohttp import web

import arena.admin.handlers as admin_handlers
from arena.admin.handlers import make_admin_handlers
from arena.admin.handlers_tunnel_exposure import (
    apply_funnel_status_url,
    audit_unified_public_stop,
    normalize_tunnel_action,
)
from arena.admin.tunnel_exposure_policy import (
    PUBLIC_TUNNEL_ACK,
    PUBLIC_TUNNEL_ACK_HEADER,
    PUBLIC_TUNNEL_PROVIDERS,
    public_start_denial,
)
from arena.app_keys import APP_CFG
from arena.handler_context import AdminHandlerContext


@pytest.mark.parametrize(
    "provider", ["tailscale", "cloudflared", "ngrok", "bore", "auto"]
)
def test_public_start_requires_exact_ack(provider: str) -> None:
    denial = public_start_denial(provider=provider, action="start", ack=None)
    assert denial == {
        "ok": False,
        "error": "tunnel_public_ack_required",
        "provider": provider,
        "required_ack": PUBLIC_TUNNEL_ACK,
        "ack_header": PUBLIC_TUNNEL_ACK_HEADER,
        "authorization_source": "api",
        "message": (
            "Starting this provider can publish the Bridge to the public "
            "internet, protected only by its bearer token."
        ),
    }
    assert public_start_denial(
        provider=provider, action="start", ack=PUBLIC_TUNNEL_ACK + " "
    ) is not None
    assert public_start_denial(
        provider=provider, action="start", ack=PUBLIC_TUNNEL_ACK
    ) is None


@pytest.mark.parametrize("action", ["status", "stop"])
def test_non_start_actions_do_not_require_ack(action: str) -> None:
    assert public_start_denial(
        provider="tailscale", action=action, ack=None
    ) is None


def test_private_overlay_and_persisted_operator_intent_do_not_require_api_ack() -> None:
    assert PUBLIC_TUNNEL_ACK == "I_ACCEPT_PUBLIC_BRIDGE_EXPOSURE"
    assert PUBLIC_TUNNEL_ACK_HEADER == "X-Arena-Public-Exposure-Ack"
    assert PUBLIC_TUNNEL_PROVIDERS == frozenset(
        {"tailscale", "cloudflared", "ngrok", "bore"}
    )
    assert public_start_denial(
        provider="zerotier", action="start", ack=None
    ) is None
    assert public_start_denial(
        provider="tailscale",
        action="start",
        ack=None,
        authorization_source="operator_persisted",
    ) is None


class _Request:
    def __init__(
        self,
        *,
        method: str = "POST",
        action: str = "start",
        body: Any = None,
        ack_header: str | None = None,
    ) -> None:
        self.method = method
        self.path = "/test"
        self.app = web.Application()
        self.app[APP_CFG] = {"port": 8765, "token": "t"}
        self.match_info = {"action": action}
        self.query = {}
        self.remote = "127.0.0.1"
        self._body = body
        self.headers = {"Authorization": "Bearer t"}
        if ack_header is not None:
            self.headers[PUBLIC_TUNNEL_ACK_HEADER] = ack_header

    async def json(self) -> Any:
        if self._body is None:
            raise ValueError("no JSON body")
        return self._body


def _context(tmp_path: Path) -> tuple[AdminHandlerContext, list[dict], list[dict]]:
    audits: list[dict] = []
    records: list[dict] = []

    def response(payload, **kwargs):
        return web.json_response(payload, status=kwargs.get("status", 200))

    context = AdminHandlerContext(
        require_auth=lambda _request: None,
        record_request=lambda **kwargs: records.append(kwargs),
        cors_json_response=response,
        executor=None,
        audit=audits.append,
        default_token_file=tmp_path / "token.txt",
        root_agent=tmp_path,
        subprocess_kwargs=lambda: {},
        tailscale_funnel_action_sync=lambda _action, _port: {
            "ok": True,
            "url": "https://bridge.example.ts.net",
        },
        cloudflared_funnel_action_sync=lambda _action, _port: {"ok": True},
        sys_funnel_status_sync=lambda: {
            "tailscale": {"connected": True},
            "funnel": {
                "active": True,
                "url": "https://bridge.example.ts.net",
            },
        },
        cloudflared_status_sync=lambda: {"active": False},
        zerotier_status_sync=lambda: {"zerotier": {}, "networks": []},
    )
    return context, audits, records


def _payload(response: web.Response) -> dict[str, Any]:
    return json.loads(response.body.decode("utf-8"))


def test_unified_start_denies_before_any_provider_call(tmp_path: Path) -> None:
    context, audits, records = _context(tmp_path)
    calls = []
    context = AdminHandlerContext(
        **{
            **context.__dict__,
            "tailscale_funnel_action_sync": lambda action, port: calls.append(
                (action, port)
            ),
        }
    )
    handlers = make_admin_handlers(context)
    response = asyncio.run(handlers.tunnels_start(_Request()))

    assert response.status == 403
    assert _payload(response)["error"] == "tunnel_public_ack_required"
    assert calls == []
    assert records == [
        {},
        {"is_error": True, "count_request": False},
    ]
    assert audits == [
        {"type": "tunnel_public_ack_denied", "provider": "auto", "action": "start"}
    ]


def test_unified_start_accepts_json_ack_and_audits_public_open(tmp_path: Path) -> None:
    context, audits, records = _context(tmp_path)
    handlers = make_admin_handlers(context)
    response = asyncio.run(
        handlers.tunnels_start(_Request(body={"ack": PUBLIC_TUNNEL_ACK}))
    )

    assert response.status == 200
    payload = _payload(response)
    assert payload["active"]["provider"] == "tailscale"
    assert records == [{}]
    assert {"type": "tunnel_public_opened", "provider": "tailscale",
            "public_url": "https://bridge.example.ts.net"} in audits


def test_provider_start_accepts_header_and_stop_needs_no_ack(
    tmp_path: Path, monkeypatch
) -> None:
    calls = []

    def action(verb: str, port: int) -> dict[str, Any]:
        calls.append((verb, port))
        return {"ok": True, "url": "https://bridge.example.ts.net"}

    monkeypatch.setattr(admin_handlers, "tailscale_funnel_action", action)
    context, audits, records = _context(tmp_path)
    handlers = make_admin_handlers(context)

    started = asyncio.run(
        handlers.tailscale_funnel(
            _Request(ack_header=PUBLIC_TUNNEL_ACK)
        )
    )
    stopped = asyncio.run(
        handlers.tailscale_funnel(_Request(action="stop"))
    )

    assert started.status == 200
    assert stopped.status == 200
    assert calls == [("start", 8765), ("stop", 8765)]
    assert records == [{}, {}]
    assert {"type": "tunnel_public_opened", "provider": "tailscale",
            "public_url": "https://bridge.example.ts.net"} in audits
    assert {"type": "tunnel_public_closed", "provider": "tailscale"} in audits


@pytest.mark.parametrize(
    "handler_name, provider",
    [
        ("tailscale_funnel", "tailscale"),
        ("cloudflared_tunnel", "cloudflared"),
        ("ngrok_tunnel", "ngrok"),
        ("bore_tunnel", "bore"),
    ],
)
def test_every_public_provider_handler_denies_unacknowledged_start(
    tmp_path: Path, handler_name: str, provider: str
) -> None:
    context, audits, _records = _context(tmp_path)
    handlers = make_admin_handlers(context)
    response = asyncio.run(getattr(handlers, handler_name)(_Request()))
    assert response.status == 403
    assert _payload(response)["provider"] == provider
    assert audits[-1] == {
        "type": "tunnel_public_ack_denied",
        "provider": provider,
        "action": "start",
    }


def test_get_start_requires_header_not_query_or_body(tmp_path: Path) -> None:
    context, _audits, _records = _context(tmp_path)
    handlers = make_admin_handlers(context)
    denied = asyncio.run(
        handlers.tailscale_funnel(
            _Request(method="GET", body={"ack": PUBLIC_TUNNEL_ACK})
        )
    )
    assert denied.status == 403


def test_public_autostart_enable_requires_ack_and_records_authorization(
    tmp_path: Path,
) -> None:
    context, audits, _records = _context(tmp_path)
    handlers = make_admin_handlers(context)

    denied_request = _Request(body={"enabled": True})
    denied_request.match_info = {"transport": "ngrok"}
    denied = asyncio.run(handlers.autostart_set(denied_request))
    assert denied.status == 403
    assert not tmp_path.joinpath(".ngrok_autostart").exists()

    accepted_request = _Request(
        body={"enabled": True, "ack": PUBLIC_TUNNEL_ACK}
    )
    accepted_request.match_info = {"transport": "ngrok"}
    accepted = asyncio.run(handlers.autostart_set(accepted_request))
    assert accepted.status == 200
    assert tmp_path.joinpath(".ngrok_autostart").exists()
    assert {
        "type": "tunnel_public_autostart_authorized",
        "provider": "ngrok",
        "changed": True,
    } in audits


@pytest.mark.parametrize(
    "ack",
    ["", "short", "I_ACCEPT_PUBLIC_BRIDGE_EXPOSUREx", "x" * 38],
)
def test_mismatched_ack_length_is_denial_not_valueerror(ack: str) -> None:
    """hmac.compare_digest raises ValueError on length mismatch.

    Without the length guard that becomes HTTP 500 instead of 403.
    """
    try:
        denial = public_start_denial(
            provider="tailscale", action="start", ack=ack
        )
    except ValueError as exc:
        raise AssertionError(
            f"ack length {len(ack)} raised ValueError: {exc}"
        ) from exc
    assert denial is not None
    assert denial["error"] == "tunnel_public_ack_required"


def test_same_length_wrong_ack_is_denial() -> None:
    wrong = "X" * len(PUBLIC_TUNNEL_ACK)
    assert len(wrong) == len(PUBLIC_TUNNEL_ACK)
    assert public_start_denial(
        provider="ngrok", action="start", ack=wrong
    ) is not None


@pytest.mark.parametrize(
    "ack",
    [
        None,
        0,
        1,
        b"I_ACCEPT_PUBLIC_BRIDGE_EXPOSURE",
        ["I_ACCEPT_PUBLIC_BRIDGE_EXPOSURE"],
        {"ack": "I_ACCEPT_PUBLIC_BRIDGE_EXPOSURE"},
    ],
)
def test_non_string_ack_is_denial(ack: Any) -> None:
    assert public_start_denial(
        provider="bore", action="start", ack=ack
    ) is not None


def test_action_and_provider_are_normalized_before_gate() -> None:
    assert normalize_tunnel_action("START") == "start"
    assert normalize_tunnel_action(" Start ") == "start"
    assert normalize_tunnel_action(None) == "status"
    assert public_start_denial(
        provider="Tailscale", action="START", ack=None
    ) is not None
    assert public_start_denial(
        provider="Tailscale", action="START", ack=PUBLIC_TUNNEL_ACK
    ) is None


def test_nonempty_wrong_header_is_not_overridden_by_body(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(
        admin_handlers,
        "tailscale_funnel_action",
        lambda _action, _port: {"ok": True},
    )
    context, audits, _records = _context(tmp_path)
    handlers = make_admin_handlers(context)
    response = asyncio.run(
        handlers.tailscale_funnel(
            _Request(body={"ack": PUBLIC_TUNNEL_ACK}, ack_header="nope")
        )
    )
    assert response.status == 403
    assert _payload(response)["error"] == "tunnel_public_ack_required"
    assert audits[-1]["type"] == "tunnel_public_ack_denied"


def test_query_string_ack_is_ignored(tmp_path: Path) -> None:
    context, _audits, _records = _context(tmp_path)
    handlers = make_admin_handlers(context)
    request = _Request()
    request.query = {"ack": PUBLIC_TUNNEL_ACK}
    response = asyncio.run(handlers.tailscale_funnel(request))
    assert response.status == 403


def test_get_start_accepts_header_and_copies_funnel_url(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(
        admin_handlers,
        "tailscale_funnel_action",
        lambda _action, _port: {"ok": True},
    )
    context, audits, _records = _context(tmp_path)
    handlers = make_admin_handlers(context)
    response = asyncio.run(
        handlers.tailscale_funnel(
            _Request(method="GET", ack_header=PUBLIC_TUNNEL_ACK)
        )
    )
    assert response.status == 200
    payload = _payload(response)
    assert payload["public_url"] == "https://bridge.example.ts.net"
    assert {
        "type": "tunnel_public_opened",
        "provider": "tailscale",
        "public_url": "https://bridge.example.ts.net",
    } in audits
    assert tmp_path.joinpath(".tailscale_autostart").exists()


def test_uppercase_start_audits_opened(tmp_path: Path, monkeypatch) -> None:
    seen: list[str] = []

    def action(verb: str, port: int) -> dict[str, Any]:
        seen.append(verb)
        return {"ok": True}

    monkeypatch.setattr(admin_handlers, "tailscale_funnel_action", action)
    context, audits, _records = _context(tmp_path)
    handlers = make_admin_handlers(context)
    response = asyncio.run(
        handlers.tailscale_funnel(
            _Request(action="START", ack_header=PUBLIC_TUNNEL_ACK)
        )
    )
    assert response.status == 200
    assert seen == ["start"]
    assert any(event.get("type") == "tunnel_public_opened" for event in audits)


def test_existing_result_url_is_not_overwritten(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(
        admin_handlers,
        "tailscale_funnel_action",
        lambda _action, _port: {"ok": True, "url": "https://already.example"},
    )
    context, audits, _records = _context(tmp_path)
    handlers = make_admin_handlers(context)
    response = asyncio.run(
        handlers.tailscale_funnel(_Request(ack_header=PUBLIC_TUNNEL_ACK))
    )
    assert response.status == 200
    assert _payload(response)["url"] == "https://already.example"
    assert {
        "type": "tunnel_public_opened",
        "provider": "tailscale",
        "public_url": "https://already.example",
    } in audits


def test_apply_funnel_status_url_is_best_effort() -> None:
    keep = {"ok": True, "url": "https://keep.example"}
    apply_funnel_status_url(keep, {"funnel": {"url": "https://other.example"}})
    assert keep["url"] == "https://keep.example"

    empty: dict[str, Any] = {"ok": True}
    apply_funnel_status_url(empty, None)
    apply_funnel_status_url(empty, "nope")
    apply_funnel_status_url(empty, {"funnel": "nope"})
    apply_funnel_status_url(empty, {"funnel": {"url": "   "}})
    assert "url" not in empty
    apply_funnel_status_url(
        empty, {"funnel": {"url": "https://from-status.example.ts.net"}}
    )
    assert empty["url"] == "https://from-status.example.ts.net"
    assert empty["public_url"] == "https://from-status.example.ts.net"


def test_unified_stop_does_not_claim_undriven_providers() -> None:
    events: list[dict] = []

    class _Ctx:
        def audit(self, event: dict) -> None:
            events.append(event)

    audit_unified_public_stop(
        _Ctx(),
        {
            "log": [
                {
                    "provider": "tailscale",
                    "action": "stop",
                    "result": {"ok": True},
                },
                {
                    "provider": "ngrok",
                    "action": "status",
                    "result": {"ok": True},
                },
            ]
        },
    )
    assert events == [
        {"type": "tunnel_public_closed", "provider": "tailscale"}
    ]


def test_security_md_documents_403_contract() -> None:
    text = (
        Path(__file__).resolve().parents[1] / "SECURITY.md"
    ).read_text(encoding="utf-8")
    assert "HTTP **403**" in text
    assert "tunnel_public_ack_required" in text
    assert "X-Arena-Public-Exposure-Ack" in text


def test_dashboard_sends_canonical_ack_after_confirm() -> None:
    js = (
        Path(__file__).resolve().parents[1]
        / "dashboard"
        / "assets"
        / "20-transports.js"
    ).read_text(encoding="utf-8")
    assert "I_ACCEPT_PUBLIC_BRIDGE_EXPOSURE" in js
    assert "I_ACCEPT_PUBLIC_EXPOSURE" not in js
    assert "window.confirm(" in js
    assert 'JSON.stringify({ack: "I_ACCEPT_PUBLIC_BRIDGE_EXPOSURE"})' in js
    assert "alreadyConfirmed" in js
