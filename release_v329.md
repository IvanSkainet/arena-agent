# v3.2.9 — KWin active-window retries

Another small KDE/Wayland polish release.

The live Plasma bridge still showed an intermittent case where KWin's
`queryWindowInfo` returned an empty payload once, causing
`/v1/desktop/active_window` to fall back to `xdotool` even though the native
KWin path worked on the next call.

## 🛠 Fixed

`/v1/desktop/active_window` now retries KWin DBus active-window lookup up to
three times with a tiny delay before falling back.

This reduces noisy false fallbacks on live KDE/Wayland sessions without changing
behavior on systems where KWin really is unavailable.

## ✅ Validation
- **552 tests pass**
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

**Full changelog**: https://github.com/IvanSkainet/arena-agent/compare/v3.2.8...v3.2.9
