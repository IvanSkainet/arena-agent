# v3.2.10 — native KWin fallback for active-window detection

Follow-up KDE/Wayland reliability release.

The live bridge showed that `org.kde.KWin.queryWindowInfo` can sometimes fail
with `org.kde.KWin.Error.UserCancel`, even though the bridge already has a
working native KWin journal-based window listing path.

## 🛠 Fixed

`/v1/desktop/active_window` now does this on KDE/Wayland:
1. try direct KWin `queryWindowInfo`
2. if that cancels / returns no usable info, use the native KWin window list
3. only then fall back to `xdotool`

This makes active-window discovery much more consistent without losing the
existing cross-desktop fallbacks.

## ✅ Validation
- **553 tests pass**
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

**Full changelog**: https://github.com/IvanSkainet/arena-agent/compare/v3.2.9...v3.2.10
