# v3.2.11 — remove interactive KWin focus stealing

Hotfix release for the KDE/Wayland desktop integration.

A live regression report showed that the bridge could periodically steal focus
and turn the cursor into a crosshair-like picker. The root cause was the direct
KWin DBus `queryWindowInfo` path used for active-window detection.

## 🛠 Fixed

### No more interactive KWin picker
`/v1/desktop/active_window` no longer uses the interactive KWin DBus query path.
It now relies on the already-working non-interactive native KWin journal-based
window list and returns the active entry from there.

### `loadScript=0` is now treated correctly
On the live Plasma session, `qdbus6 ... loadScript ...` could return `0` even
though the script still executed successfully. The bridge now treats the DBus
call itself as success and validates execution by waiting for journal output.

### Capability map aligned with runtime behavior
`/v1/capabilities` now reports `kwin_journal` for both:
- desktop window listing
- active window discovery

## ✅ Validation
- **552 tests pass**
- `bash -n install.sh` — PASS
- `python -m py_compile ...` — PASS
- `ruff check . --select F821,F811` — PASS

## 📦 Upgrade
```bash
cd ~/arena-bridge
git pull --ff-only
./install.sh
systemctl --user restart arena-bridge.service
```

**Full changelog**: https://github.com/IvanSkainet/arena-agent/compare/v3.2.10...v3.2.11
