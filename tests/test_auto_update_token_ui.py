"""Regression guards for v4.50.0 -- UI-configured GitHub token.

Windows operators previously had to edit systemd overrides / nssm
Environment tabs to enable SHA-256 verified auto-updates. Ivan tested
Windows and hit exactly this wall: "Auto Update чисто для галочки
стоит, инструкций нет, GITHUB_TOKEN обязательно требует, нигде он
токен не видит и не принимает". Fix: token is now settable from the
Dashboard Settings tab, persisted to <install_root>/.github_token
(dotfile so a self-update never overwrites it), 0600 perms.

Endpoints (both master-token-authed like the rest of /v1/admin/*):

* POST /v1/admin/update/token-set   { token: str }  -> {ok, path, source}
* POST /v1/admin/update/token-clear                  -> {ok, removed, path}

Resolution precedence (unchanged fallbacks + new file):
  GITHUB_TOKEN env  >  GH_TOKEN env  >  <install_root>/.github_token file

`handle_update_status` now reports `github_token_source` in
{env, file, none} so the UI can show a live badge instead of a
generic "add GITHUB_TOKEN" instructions block.
"""
from __future__ import annotations

import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def _read(rel: str) -> str:
    return (REPO_ROOT / rel).read_text(encoding="utf-8")


def test_update_github_helper_has_save_and_clear_functions():
    src = _read("arena/admin/update_github.py")
    for sym in (
        "def _token_file_path()",
        "def _read_token_file()",
        "def github_token()",
        "def github_token_source()",
        "def save_github_token(",
        "def clear_github_token()",
    ):
        assert sym in src, f"update_github.py must define {sym}"


def test_github_token_reads_file_when_env_missing(tmp_path, monkeypatch):
    """github_token() must fall through to the file when both env
    vars are absent. This is the whole point of the v4.50.0 fix."""
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("GH_TOKEN", raising=False)

    from arena.admin import update_github as ug

    fake_file = tmp_path / ".github_token"
    fake_file.write_text("# header\nghp_" + "x" * 36 + "\n", encoding="utf-8")

    monkeypatch.setattr(ug, "_token_file_path", lambda: fake_file)

    tok = ug.github_token()
    assert tok is not None and tok.startswith("ghp_")
    assert ug.github_token_source() == "file"


def test_env_wins_over_file(tmp_path, monkeypatch):
    from arena.admin import update_github as ug
    fake_file = tmp_path / ".github_token"
    fake_file.write_text("ghp_" + "f" * 36, encoding="utf-8")
    monkeypatch.setattr(ug, "_token_file_path", lambda: fake_file)
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_" + "e" * 36)
    assert ug.github_token().startswith("ghp_e")
    assert ug.github_token_source() == "env"


def test_source_is_none_when_no_env_and_no_file(tmp_path, monkeypatch):
    from arena.admin import update_github as ug
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("GH_TOKEN", raising=False)
    monkeypatch.setattr(ug, "_token_file_path", lambda: tmp_path / "missing")
    assert ug.github_token() is None
    assert ug.github_token_source() == "none"


def test_save_rejects_whitespace_and_empty(tmp_path, monkeypatch):
    from arena.admin import update_github as ug
    monkeypatch.setattr(ug, "_token_file_path", lambda: tmp_path / ".github_token")
    assert not ug.save_github_token("").get("ok")
    assert not ug.save_github_token("   ").get("ok")
    # Whitespace inside is a bad paste signal:
    assert not ug.save_github_token("ghp_aa bb").get("ok")
    # Too short:
    assert not ug.save_github_token("x").get("ok")
    # Valid:
    ok = ug.save_github_token("ghp_" + "a" * 40)
    assert ok.get("ok") and ok.get("path")


def test_save_uses_atomic_replace(tmp_path, monkeypatch):
    """Simulate a token save then verify the file lands with 0600
    perms on POSIX and contains the token. Windows silently ignores
    chmod but the file must still be present + parsable."""
    from arena.admin import update_github as ug
    target = tmp_path / ".github_token"
    monkeypatch.setattr(ug, "_token_file_path", lambda: target)
    res = ug.save_github_token("ghp_" + "z" * 40)
    assert res.get("ok")
    assert target.exists()
    body = target.read_text(encoding="utf-8")
    assert "ghp_" in body
    # chmod is best-effort; on POSIX we expect 0600. Skip strict check
    # on Windows where os.chmod is largely a no-op for mode bits.
    if os.name == "posix":
        mode = target.stat().st_mode & 0o777
        assert mode == 0o600, f"expected 0o600, got {oct(mode)}"


def test_clear_removes_file_but_is_idempotent(tmp_path, monkeypatch):
    from arena.admin import update_github as ug
    target = tmp_path / ".github_token"
    monkeypatch.setattr(ug, "_token_file_path", lambda: target)
    # First clear when nothing exists is a no-op but still ok.
    r0 = ug.clear_github_token()
    assert r0.get("ok") and not r0.get("removed")
    # Save + clear works.
    ug.save_github_token("ghp_" + "y" * 40)
    r1 = ug.clear_github_token()
    assert r1.get("ok") and r1.get("removed")
    assert not target.exists()


def test_two_new_routes_are_registered():
    """v4.50.0: the new endpoints must live in the central registry
    AND the flat aiohttp binder AND be handed to the AdminHandlers
    dataclass. Miss any one and the route 404s."""
    reg = _read("arena/route_registry/registry.py")
    core = _read("arena/route_registry/core.py")
    plat = _read("arena/wiring/platform.py")
    hdlrs = _read("arena/admin/handlers.py")
    hup = _read("arena/admin/handlers_update.py")

    assert "/v1/admin/update/token-set" in reg
    assert "/v1/admin/update/token-clear" in reg
    assert "/v1/admin/update/token-set" in core
    assert "/v1/admin/update/token-clear" in core
    assert "handle_v1_admin_update_token_set" in plat
    assert "handle_v1_admin_update_token_clear" in plat
    assert "update_token_set: object" in hdlrs
    assert "update_token_clear: object" in hdlrs
    assert "update_token_set=_upd" in hdlrs
    assert "update_token_clear=_upd" in hdlrs
    assert "handle_update_token_set" in hup
    assert "handle_update_token_clear" in hup


def test_settings_body_has_token_form_not_just_instructions():
    """The Settings tab must ship an actual UI form (input + Save +
    Clear + status text), not just the old <details> instructions."""
    body = _read("dashboard/assets/body-15-settings.html")
    for marker in (
        "adminUpdateTokenInput",
        "adminUpdateTokenStatus",
        "adminUpdateTokenResult",
        "adminUpdateTokenSave()",
        "adminUpdateTokenClear()",
        "GitHub token for verified installs",
    ):
        assert marker in body, f"Settings body must include {marker!r}"


def test_admin_update_js_has_token_handlers():
    js = _read("dashboard/assets/39-admin-update.js")
    for sym in (
        "async function adminUpdateTokenSave",
        "async function adminUpdateTokenClear",
        "_adminUpdateRefreshTokenStatus",
        "/v1/admin/update/token-set",
        "/v1/admin/update/token-clear",
    ):
        assert sym in js, f"admin-update JS must define {sym!r}"
    # Should use the existing api() helper (not raw fetch or a
    # made-up arenaFetch()) so BASE + headers stay consistent.
    assert "arenaFetch(" not in js, "must use api() helper, not arenaFetch"


def test_status_handler_reports_token_source():
    src = _read("arena/admin/handlers_update.py")
    assert "github_token_source" in src, (
        "handle_update_status must include github_token_source in payload"
    )
    assert '"github_token_source"' in src or "'github_token_source'" in src


def test_install_disabled_tooltip_points_at_token_box():
    """When SHA-256 is unavailable, the tooltip must now point at the
    new Token box, not at the outdated systemd instructions."""
    js = _read("dashboard/assets/39-admin-update.js")
    assert "paste a github token" in js.lower() or "paste it into the" in js.lower(), (
        "the install-disabled tooltip must guide the operator to "
        "paste a token, not point at systemd only"
    )
