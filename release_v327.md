# v3.2.7 — native KDE window listing actually fixed

Follow-up release after v3.2.6.

The live runtime audit showed that the bridge no longer returned an empty window list on KDE/Wayland, but it was still falling back to `xdotool` because the native KWin script path silently failed: `loadScript` returned `0` for the generated helper script.

## 🛠 Fixed

### Native `/v1/desktop/windows`
The generated KWin helper script no longer tries to unload itself via:

```js
callDBus(..., 'unloadScript', ...)
```

That line was enough to make KWin reject the script on the live Plasma session, so the bridge always fell back to `xdotool`.

The script is now kept simple:
- emit JSON to the journal
- let Python unload the script in `finally`

Result: native KWin window listing works as intended.

### Capability map accuracy
On KDE/Wayland, `/v1/capabilities` now reports:
- `desktop.windows.backend = kwin_journal`
- `desktop.active_window.backend = kwin_dbus`

instead of pretending both operations use the same backend.

## ✅ Validation
- **550 tests pass**
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

**Full changelog**: https://github.com/IvanSkainet/arena-agent/compare/v3.2.6...v3.2.7
