# v3.2.12 — rate limiter race-condition fix

Small correctness release.

A code review of the v2 rate limiter found that `_rl_v2_store[user_id]` cleanup
was happening after `_rl_v2_lock` had already been released, which opened a
real concurrent mutation window.

## 🛠 Fixed

`arena/rate_limit.py::check_rate_limit_v2()` now keeps shared-store cleanup
inside the lock.

Before:
- append request timestamp while holding the lock
- release lock
- prune empty endpoint entries / possibly delete user bucket outside the lock

Now:
- append request timestamp
- prune endpoint map
- delete empty user bucket if needed
- only then release the lock

## ✅ Validation
- **553 tests pass**
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

**Full changelog**: https://github.com/IvanSkainet/arena-agent/compare/v3.2.11...v3.2.12
