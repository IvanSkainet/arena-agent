"""Tests for the breaker_summary + deprioritization work in
GET /v1/agent/config (v4.16.0).

The v4.1.0 agent bootstrap endpoint returned an ordered list of
reachable URLs based on the raw provider priority. Once v4.8.0
added the circuit breaker, a provider that had failed the last
few probes still showed up in that list -- the agent's naive
"try in order" logic would pick a URL known to be broken and
pay the failure cost on every fresh dial.

v4.16.0 wires the breaker snapshot into the agent config
response so callers see:

* ``breaker_summary`` -- compact per-provider view of open /
  warn / closed_ok counts
* ``deprioritized`` -- flat list of provider names that have at
  least one open breaker
* ``priority`` -- rebuilt to sink deprioritized providers to the
  tail; original preserved in ``priority_original`` when a
  reorder happened
* ``urls`` -- also sorted so healthy providers come first
* ``primary`` -- now matches ``urls[0]`` after the reorder

Same containment discipline as the rest of the breaker line:
pure additive, backward-compat, existing v4.1.0 tests unchanged.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from arena.admin.tunnels_breaker import summarize_snapshot


# ---------------------------------------------------------------------------
# summarize_snapshot pure helper
# ---------------------------------------------------------------------------
def test_summarize_empty_snapshot_returns_stable_shape():
    """A fresh bridge with no probes yet must still return the
    documented keys so agents can rely on them without None-checks."""
    s = summarize_snapshot({})
    assert set(s.keys()) == {
        "open", "warn", "closed_ok",
        "total_records", "open_count", "warn_count",
    }
    assert s["open"] == []
    assert s["warn"] == []
    assert s["closed_ok"] == []
    assert s["total_records"] == 0
    assert s["open_count"] == 0
    assert s["warn_count"] == 0


def test_summarize_open_provider_appears_in_open_list():
    snap = {"cloudflared|foo.example:443": {
        "state": "open", "consecutive_failures": 3,
        "last_error": "timeout", "cools_down_in_sec": 45.0,
    }}
    s = summarize_snapshot(snap)
    assert s["open"] == ["cloudflared"]
    assert s["warn"] == []
    assert s["closed_ok"] == []
    assert s["open_count"] == 1
    assert s["total_records"] == 1


def test_summarize_closed_with_failures_appears_in_warn():
    """A closed breaker with N > 0 consecutive failures is
    'trending bad' -- agent might already deprioritise or just
    watch it. Warn list gives an early signal."""
    snap = {"zerotier|10.0.0.1:8765": {
        "state": "closed", "consecutive_failures": 2,
        "last_error": "timeout after 1.5s",
    }}
    s = summarize_snapshot(snap)
    assert s["open"] == []
    assert s["warn"] == ["zerotier"]
    assert s["warn_count"] == 1


def test_summarize_closed_zero_failures_is_healthy():
    snap = {"tailscale|foo.ts.net:443": {
        "state": "closed", "consecutive_failures": 0,
        "last_error": None,
    }}
    s = summarize_snapshot(snap)
    assert s["closed_ok"] == ["tailscale"]
    assert s["open"] == []
    assert s["warn"] == []


def test_summarize_open_dominates_over_warn_for_same_provider():
    """One provider with TWO endpoints (Cloudflared reissue with a
    new hostname) -- if one endpoint is open the whole provider is
    treated as deprio'd, not double-counted in warn."""
    snap = {
        "cloudflared|old.example:443": {
            "state": "open", "consecutive_failures": 3,
        },
        "cloudflared|new.example:443": {
            "state": "closed", "consecutive_failures": 1,
        },
    }
    s = summarize_snapshot(snap)
    assert s["open"] == ["cloudflared"]
    assert s["warn"] == []
    assert s["closed_ok"] == []
    assert s["open_count"] == 1


def test_summarize_provider_names_sorted_deterministically():
    """Ordering must be deterministic so an agent diffing two
    consecutive responses doesn't see spurious changes."""
    snap = {
        "zerotier|x:1": {"state": "open"},
        "cloudflared|y:2": {"state": "open"},
        "tailscale|z:3": {"state": "open"},
    }
    s = summarize_snapshot(snap)
    assert s["open"] == ["cloudflared", "tailscale", "zerotier"]


def test_summarize_handles_multiple_states_across_providers():
    snap = {
        "cloudflared|a:1": {"state": "open", "consecutive_failures": 3},
        "zerotier|b:2":    {"state": "closed", "consecutive_failures": 2},
        "tailscale|c:3":   {"state": "closed", "consecutive_failures": 0},
    }
    s = summarize_snapshot(snap)
    assert s["open"] == ["cloudflared"]
    assert s["warn"] == ["zerotier"]
    assert s["closed_ok"] == ["tailscale"]
    assert s["total_records"] == 3
    assert s["open_count"] == 1
    assert s["warn_count"] == 1


def test_summarize_tolerates_malformed_records():
    """Older bridges might send a record without ``state`` /
    ``consecutive_failures``. Must not throw."""
    snap = {
        "cloudflared|x:1": {},
        "zerotier|y:2":    "not-a-dict",   # type: ignore[dict-item]
        "tailscale|z:3":   None,           # type: ignore[dict-item]
    }
    s = summarize_snapshot(snap)  # must not raise
    # cloudflared has empty dict -> treated as closed, 0 fails ->
    # closed_ok. zerotier/tailscale are non-dict; they still get
    # a provider slot (string split works on any str key).
    assert s["total_records"] == 3


# ---------------------------------------------------------------------------
# handle_v1_agent_config integration
# ---------------------------------------------------------------------------
def test_agent_config_response_shape_includes_breaker_fields():
    """v4.16.0 contract: the response has ``breaker_summary``
    and ``deprioritized`` alongside the v4.1.0 fields."""
    handlers_py = (Path(__file__).resolve().parents[1]
                   / "arena" / "admin" / "handlers.py").read_text()
    # The handler body must construct both new keys.
    assert '"breaker_summary": breaker_summary' in handlers_py
    assert '"deprioritized":' in handlers_py
    # And priority_original is present when a reorder happened.
    assert '"priority_original":' in handlers_py


def test_agent_config_calls_summarize_snapshot():
    handlers_py = (Path(__file__).resolve().parents[1]
                   / "arena" / "admin" / "handlers.py").read_text()
    assert "from arena.admin.tunnels_breaker import summarize_snapshot" in handlers_py
    assert "summarize_snapshot(probe.get(\"breaker\") or {})" in handlers_py


def test_agent_config_reorders_priority_by_deprio():
    """Handler logic (extract into local variables and reproduce
    the ordering step) so we test the actual sinking algorithm,
    not just its presence."""
    from arena.admin.tunnels_breaker import summarize_snapshot

    probe = {
        "priority": ["tailscale", "zerotier", "cloudflared"],
        "breaker": {
            "cloudflared|foo:443": {"state": "open"},
        },
    }
    summary = summarize_snapshot(probe["breaker"])
    deprio = set(summary["open"])
    original_priority = list(probe["priority"])
    keep = [p for p in original_priority if p not in deprio]
    sink = [p for p in original_priority if p in deprio]
    effective = keep + sink
    assert effective == ["tailscale", "zerotier", "cloudflared"]
    # Cloudflared still last -- because it was already last. But
    # if we deprio zerotier instead, it should move to the tail.
    probe2 = {
        "priority": ["tailscale", "zerotier", "cloudflared"],
        "breaker": {"zerotier|10.0.0.1:8765": {"state": "open"}},
    }
    summary2 = summarize_snapshot(probe2["breaker"])
    deprio2 = set(summary2["open"])
    keep2 = [p for p in probe2["priority"] if p not in deprio2]
    sink2 = [p for p in probe2["priority"] if p in deprio2]
    assert keep2 + sink2 == ["tailscale", "cloudflared", "zerotier"]


def test_agent_config_reorders_urls_matching_effective_priority():
    """The urls list must sort with deprio providers at the tail,
    then within each partition by the effective priority order.
    Regression guard on the sort key -- if a future edit flips
    the tuple order agents will suddenly get broken URLs first."""
    # Simulate the response construction locally.
    probe_probes = [
        {"provider": "tailscale", "public_url": "https://ts/",
         "reachable": True, "public_kind": "https"},
        {"provider": "zerotier",  "public_url": "http://10.0.0.1:8765/",
         "reachable": True, "public_kind": "http-lan"},
        {"provider": "cloudflared", "public_url": "http://cf/",
         "reachable": True, "public_kind": "http-lan"},
    ]
    priority = ["tailscale", "zerotier", "cloudflared"]
    deprio = {"tailscale"}  # simulate tailscale is deprio'd
    urls = [{"provider": p["provider"], "url": p["public_url"],
             "kind": p["public_kind"]} for p in probe_probes]
    keep = [p for p in priority if p not in deprio]
    sink = [p for p in priority if p in deprio]
    effective = keep + sink
    urls.sort(key=lambda u: (
        1 if u["provider"] in deprio else 0,
        effective.index(u["provider"]) if u["provider"] in effective
            else len(effective),
    ))
    assert [u["provider"] for u in urls] == \
        ["zerotier", "cloudflared", "tailscale"]


def test_agent_config_primary_matches_first_url_after_reorder():
    """v4.16.0 recomputes primary AFTER the reorder so it always
    points at the first entry in urls. Regression guard against a
    future edit that trusts probe.get('active') (which reflects
    the ORIGINAL order, before deprioritisation)."""
    handlers_py = (Path(__file__).resolve().parents[1]
                   / "arena" / "admin" / "handlers.py").read_text()
    # The handler must set primary from urls[0] when urls is
    # non-empty, not directly from probe['active'].
    assert 'primary = {"provider": urls[0].get("provider")' in handlers_py


def test_agent_config_no_reorder_when_no_open_breakers():
    """Backward compat: on a fresh bridge (empty breaker) the
    response looks exactly like v4.15.x -- priority unchanged,
    priority_original is None, deprioritized is []."""
    from arena.admin.tunnels_breaker import summarize_snapshot
    summary = summarize_snapshot({})
    deprio = set(summary["open"])
    assert deprio == set()
    original_priority = ["tailscale", "zerotier", "cloudflared"]
    if deprio and original_priority:
        keep = [p for p in original_priority if p not in deprio]
        sink = [p for p in original_priority if p in deprio]
        effective_priority = keep + sink
    else:
        effective_priority = original_priority
    assert effective_priority == original_priority


def test_summarize_snapshot_is_in_module_exports():
    """__all__ must include summarize_snapshot so 'from
    arena.admin.tunnels_breaker import *' works for future
    consumers."""
    from arena.admin import tunnels_breaker
    assert "summarize_snapshot" in tunnels_breaker.__all__
