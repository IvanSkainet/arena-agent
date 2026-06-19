# v3.2.13 — canonical roadmap docs + stale backup cleanup

This release is mostly product/maintenance cleanup.

## 🛠 Fixed

### Removed stale backup CLI/workflow references
- `agentctl backup run` no longer tries to call the removed `/v1/backup` API.
- It now prints a clear deprecation notice telling the user to rely on external backup tools.
- Mission templates no longer emit dead backup commands in `cli-agent-core` and `recovery-drill`.

### `agentctl` version string corrected
`agentctl` now uses the canonical Arena version instead of advertising a stale hard-coded `2.0.0`.

## 📚 Docs added
- `docs/ROADMAP_CANONICAL.md`
- `docs/PRODUCT_DIRECTION.md`
- `docs/EXPERIMENTS.md`

These replace the need to treat multiple drifting roadmap snapshots as current truth.

## ✅ Validation
- **558 tests pass**
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

**Full changelog**: https://github.com/IvanSkainet/arena-agent/compare/v3.2.12...v3.2.13
