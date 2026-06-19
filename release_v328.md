# v3.2.8 — KWin active-window fallback reduction

Small follow-up after v3.2.7.

The live KDE/Wayland bridge now uses native KWin window listing correctly, but
`/v1/desktop/active_window` could still fall back to `xdotool` when KWin's
`queryWindowInfo` returned a minimal payload for helper/focus-proxy windows.

## 🛠 Fixed

`/v1/desktop/active_window` now treats any non-empty `queryWindowInfo` payload
as valid KWin data, not only payloads containing `caption` or `uuid`.

This makes active-window discovery more robust for:
- Plasma helper windows
- focus proxy windows
- small utility windows where KWin omits title/uuid but still exposes class,
  resource name, and geometry

## ✅ Validation
- **551 tests pass**
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

**Full changelog**: https://github.com/IvanSkainet/arena-agent/compare/v3.2.7...v3.2.8
