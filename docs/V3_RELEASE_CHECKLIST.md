# v3 Stable Release Checklist

Use this checklist before promoting the modular bridge from alpha/beta/RC to a
stable `v3.0.0` release.

## Architecture gates

- [ ] `unified_bridge.py` remains a thin compatibility/CLI entrypoint (`<= 150` lines preferred; hard limit `<= 200`).
- [ ] No `arena/*` module imports `unified_bridge.py`.
- [ ] No new runtime mini-monoliths above ~180-220 lines unless explicitly allowed.
- [ ] `arena/route_registry/*` owns route registration by domain.
- [ ] `arena/contexts/*` owns handler context dataclasses.
- [ ] New feature work lives in focused `arena/<domain>/` modules.
- [ ] `docs/MODULE_MAP.md` and `docs/V3_MODULAR_ARCHITECTURE.md` match the current tree.

## Local validation

```bash
pytest -q
python -m py_compile unified_bridge.py
```

Expected:

- [ ] Full test suite passes.
- [ ] No unexpected import-cycle failures.
- [ ] Compatibility surface tests pass.
- [ ] Architecture boundary tests pass.

## Live Linux validation

```bash
python dev/stress-test-v4.py \
  --url https://cachyos-x8664.tail328f18.ts.net \
  --token <token> \
  --timeout 45 \
  --restart
```

Expected:

- [ ] Live `pytest -q` passes.
- [ ] Core smoke passes: `/health`, `/v1/version`, `/v1/status`.
- [ ] Service/restart smoke passes: `/v1/service/info`, `/v1/sys/svc`, `POST /v1/restart`.
- [ ] Desktop smoke passes on KDE/Wayland: windows, active window, screenshot.
- [ ] CDP smoke passes: status/session check; diagnostics if needed.
- [ ] Stress v4 summary is `PASS=18` or documented equivalent.

## Windows validation

- [ ] Fresh install from release zip.
- [ ] `/health` and `/v1/version` report the expected version.
- [ ] `/v1/service/info` and `/v1/sys/svc` correctly identify Scheduled Task/NSSM mode.
- [ ] `/v1/hardware` and `/v1/capabilities` pass.
- [ ] `POST /v1/restart` relaunches the bridge cleanly.
- [ ] `dev/stress-test-v4.py --restart` passes against the Windows bridge.
- [ ] Uninstall removes the service/task and files cleanly.

## Packaging and release

- [ ] `arena/constants.py` and `pyproject.toml` versions match the release tag.
- [ ] Release zip contains `arena/**`, `unified_bridge.py`, installers, docs, scripts, skills and tests as intended.
- [ ] README badge/version and changelog match the release.
- [ ] GitHub release notes include validation results and migration/install guidance.
- [ ] For stable, release is not marked as prerelease.

## Current v3 promotion ledger

```text
v3.0.0-alpha.1  -> architecture complete
v3.0.0-beta.1   -> Linux/Windows modular beta validation
v3.0.0-beta.2   -> installer hotfix candidate, stale Windows service cleanup
v3.0.0-rc.1     -> release-zip/fresh-install validation gate
v3.0.0          -> stable replacement for v2.12.0 on master (validated)
```

## RC/stable promotion notes

- [ ] Tag and package `v3.0.0-rc.1` only after local tests pass.
- [ ] Fresh-install `v3.0.0-rc.1` ZIP on CachyOS/Linux.
- [ ] Fresh-install `v3.0.0-rc.1` ZIP on Windows.
- [ ] Re-run stress v4 with restart on both machines.
- [ ] Fast-forward or merge the modular v3 tree into `master` after RC validation.
- [ ] Tag stable `v3.0.0` from `master` after final smoke/stress checks.

## v3.0.0 validation summary

- [x] Windows fresh install from RC release ZIP: PASS.
- [x] Windows source `pytest -q`: PASS, 400 tests.
- [x] Windows stress v4 with restart: PASS=15 SKIP=3.
- [x] CachyOS/Linux fresh install from RC release ZIP: PASS.
- [x] CachyOS/Linux source `pytest -q`: PASS, 400 tests.
- [x] CachyOS/Linux stress v4 with restart: PASS=18.
- [x] CachyOS/Linux KDE/Wayland desktop smoke: PASS.
- [x] Tailscale Funnel public health on both platforms: PASS.
- [x] Keep `v2.12.0` available as the old monolith tag/release.
