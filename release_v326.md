# v3.2.6 — KDE/Wayland desktop fixes + AppKey cleanup

This release focuses on small-but-real paper cuts found during a live runtime audit: missing desktop session metadata in systemd-user installs, broken active-window detection on Plasma/Wayland, KWin window-listing being skipped when `XDG_CURRENT_DESKTOP` was absent, and aiohttp `NotAppKeyWarning` noise.

## 🛠 Fixed

### KDE/Wayland active window
`/v1/desktop/active_window` now uses:
- `org.kde.KWin.queryWindowInfo`

instead of outdated DBus calls that no longer worked reliably on modern Plasma.

### KWin window listing in systemd-user services
`/v1/desktop/windows` no longer requires `XDG_CURRENT_DESKTOP` / `XDG_SESSION_TYPE` to already be present before it even tries the KWin scripting path.

It now probes KWin directly over DBus first, so live services with only `WAYLAND_DISPLAY` + `DBUS_SESSION_BUS_ADDRESS` still get native KDE window enumeration.

### Session bootstrap
Linux startup now infers missing desktop metadata when possible:
- `XDG_SESSION_TYPE`
- `XDG_CURRENT_DESKTOP`
- `DESKTOP_SESSION`

This improves:
- `/v1/capabilities`
- desktop automation helpers
- systemd-user reliability on KDE/Wayland

### aiohttp AppKey cleanup
Bridge app state moved from raw string keys to shared `aiohttp.web.AppKey` definitions for:
- app config
- MCP sessions
- lifecycle tasks

This removes `NotAppKeyWarning` noise from runtime/tests and aligns the app with current aiohttp guidance.

## 📦 Installer polish
`install.sh` now persists desktop session metadata into the generated systemd user unit when those values are available during install.

## 📚 Docs
- Refreshed stale route-count wording in README/README.ru
- Refreshed desktop endpoint counts to match the current v3.2.x surface

## ✅ Validation
- **549 tests pass**
- `bash -n install.sh` — PASS
- `python -m py_compile ...` — PASS
- `python -m ruff check . --select F821,F811` — PASS

## 📦 Upgrade
```bash
cd ~/arena-bridge
git pull --ff-only
./install.sh
systemctl --user restart arena-bridge.service
```

**Full changelog**: https://github.com/IvanSkainet/arena-agent/compare/v3.2.5...v3.2.6
