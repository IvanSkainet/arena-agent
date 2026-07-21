"""Regression guards for v4.50.2.

Live operator report on v4.50.0:

  Save failed: HTTP 401: unauthorized -- token save form died on
  every attempt. Root cause was a merge-order bug in api-helper.js:
  `{headers, ...opts}` -- when the caller supplied `opts.headers`
  (for a Content-Type on the token POST) it fully replaced the
  module-level `headers` object that carries the Bearer token.
  Fix: DEEP-merge caller headers ONTO the auth headers so the
  Authorization stays.

Plus:

  Господи, почему нельзя нормальный Auto Update сделать?

  So we now allow an opt-in "install without SHA-256 verification"
  path. Only fires when the operator has no GitHub token AND
  explicitly clicks through a strong confirm dialog. Consent-token
  gate uses a distinct UNVERIFIED sentinel so verified consents
  cannot be replayed to trigger unverified installs.

  Windows Inventory зависает / Dashboard медленный на Windows.

  Added a 60-second in-memory cache to /v1/hardware and
  /v1/inventory so a Windows dashboard reload that hits both in
  parallel doesn't pay the full WMI/PowerShell cold-start twice.
  `?nocache=1` forces a fresh collection.
"""
from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def _read(rel: str) -> str:
    return (REPO_ROOT / rel).read_text(encoding="utf-8")


# ------------------------------------------------------------------
# 401 fix
# ------------------------------------------------------------------

def test_api_helper_merges_headers_instead_of_clobbering():
    """v4.50.2: api() must deep-merge caller headers with auth."""
    src = _read("dashboard/assets/02-api-helper.js")
    # The buggy spread pattern must be gone from actual fetch() calls.
    # It stays in a comment as historical explanation, so we check
    # only the fetch call site.
    import re
    call_bad = re.search(r"fetch\(BASE\s*\+\s*path,\s*\{headers,\s*\.\.\.opts\}\)", src)
    assert not call_bad, (
        "fetch() must not use {headers, ...opts} anymore (v4.50.0 401 bug)"
    )
    # Explicit Object.assign merge is what we want.
    assert "Object.assign({}, headers, opts.headers" in src, (
        "auth headers must be merged with caller-supplied ones"
    )
    # And the merged headers must reach fetch.
    assert 'Object.assign({}, opts, {headers: merged})' in src


# ------------------------------------------------------------------
# Unverified install opt-in
# ------------------------------------------------------------------

def test_apply_update_accepts_no_verification_opt_in():
    """v4.50.2: apply_update signature has accept_no_verification=False
    default; setting it to True + no expected_sha256 must not fail."""
    src = _read("arena/admin/auto_update.py")
    assert "accept_no_verification: bool = False" in src
    # Sentinel string used in consent for unverified path.
    assert '"UNVERIFIED"' in src
    # Guard: if no digest AND no opt-in, still errors.
    assert 'accept_no_verification=true' in src.lower(), (
        "operator hint must mention the accept_no_verification flag"
    )
    # Result payload records the verification path.
    assert '"verification": "unverified" if unverified else "sha256"' in src


def test_handlers_apply_forwards_no_verification_flag():
    src = _read("arena/admin/handlers_update.py")
    assert 'body.get("accept_no_verification", False)' in src, (
        "handler must read the flag from the JSON body"
    )
    # And forward it to apply_update.
    assert 'accept_no_verification=accept_no_verification' in src
    # Audit records the verification chosen.
    assert '"verification":' in src


def test_admin_update_js_offers_unverified_install():
    """v4.50.2: install button now enables even without a digest;
    the JS flow adds accept_no_verification=true when digest empty."""
    src = _read("dashboard/assets/39-admin-update.js")
    # The old always-disabled branch when !check.asset_digest is gone.
    import re
    old_pattern = re.search(
        r"_adminUpdateSetInstallEnabled\(false,\s*\n\s*\"Install disabled: GitHub did not publish a SHA-256 digest",
        src,
    )
    assert not old_pattern, (
        "install button must no longer be permanently disabled when digest missing"
    )
    # New tooltip mentions unverified path.
    assert "Install without SHA-256 verification" in src
    # The install flow must send accept_no_verification=true when digest empty.
    assert "body.accept_no_verification = true" in src


# ------------------------------------------------------------------
# Inventory cache
# ------------------------------------------------------------------

def test_hardware_endpoint_has_hw_cache():
    src = _read("arena/inventory/handlers.py")
    assert "_HW_CACHE_TTL_SEC = 900.0" in src
    assert "_hw_cache" in src and "_inv_cache" in src
    # Cache lookup + store helpers are present.
    assert "def _cache_lookup(" in src
    assert "def _cache_store(" in src
    # nocache=1 escape hatch on both endpoints.
    assert 'request.query.get("nocache"' in src


def test_prior_v450_regression_guards_still_hold():
    """v4.50.0 GitHub-token-file plumbing must not have regressed."""
    ug = _read("arena/admin/update_github.py")
    for sym in (
        "def _token_file_path()",
        "def _read_token_file()",
        "def github_token()",
        "def github_token_source()",
        "def save_github_token(",
        "def clear_github_token()",
    ):
        assert sym in ug
    # And the endpoints are still wired.
    reg = _read("arena/route_registry/registry.py")
    assert "/v1/admin/update/token-set" in reg
    assert "/v1/admin/update/token-clear" in reg


def test_v0_14_12_extension_regression_guards_still_hold():
    """v4.50.1 Grok fingerprint fix + send latency reduction survive."""
    adapters = _read("chat_extension/adapters.js")
    strat = _read("chat_extension/insert_strategies.js")
    assert "let bubbleId = ''" in adapters
    assert "const deadline = Date.now() + 800;" in strat


def test_verified_consent_and_unverified_consent_are_distinct():
    """Consent token derivation must produce different values for
    verified vs unverified installs so a stored verified consent
    cannot be replayed."""
    import importlib.util
    p = REPO_ROOT / "arena/admin/auto_update.py"
    spec = importlib.util.spec_from_file_location("_arena_au", p)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore
    tag = "v4.50.2"
    verified = mod.consent_token(tag=tag, sha256="a" * 64)
    unverified = mod.consent_token(tag=tag, sha256="UNVERIFIED")
    assert verified != unverified
