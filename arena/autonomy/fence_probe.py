"""Does a sandbox fence actually work here, or is it merely installed?

Split out of ``arena/autonomy/runner.py`` to keep that module under the
mini-monolith line threshold enforced by
``tests/test_architecture_boundaries.py``. One concern lives here: answering
"can this host really engage the fence", by trying it rather than by looking
for a binary.

``shutil.which("systemd-run")`` answers "is it installed", which is not the
question. In a container, an SSH session without lingering, or anywhere with
no D-Bus session bus, the binary is present and every invocation fails with
"Failed to connect to user scope bus". Reporting the fence as engaged on that
evidence turns a clear "this fence is unavailable here" into a confusing
error from the child process, several layers later. Fail-closed has to mean
the fence *works*.
"""
from __future__ import annotations

import os
import subprocess

# Cached for the process: this sits on the hot path of every sandboxed run,
# and the answer cannot change without the host changing.
_SYSTEMD_PROBE: tuple[bool, str] | None = None


def reset_cache() -> None:
    """Forget the probe result (tests, and hosts that gain a session bus)."""
    global _SYSTEMD_PROBE
    _SYSTEMD_PROBE = None


def systemd_run_works() -> tuple[bool, str]:
    """Return (works, reason_if_not) for ``systemd-run --user``."""
    global _SYSTEMD_PROBE
    if _SYSTEMD_PROBE is not None:
        return _SYSTEMD_PROBE
    if os.environ.get("ARENA_ASSUME_SYSTEMD_FENCE") == "1":
        # Escape hatch for hosts that cannot speak for their own runtime
        # (a build container producing an image for a systemd target).
        # Opt-in only: the default stays "prove it".
        _SYSTEMD_PROBE = (True, "")
        return _SYSTEMD_PROBE
    try:
        proc = subprocess.run(  # nosec B603,B607 -- fixed argv, no shell, probe only
            ["systemd-run", "--user", "--quiet", "--collect", "--pipe",
             "--", "/bin/true"],
            capture_output=True, text=True, timeout=10,
        )
        err = [ln for ln in (proc.stderr or "").strip().splitlines() if ln.strip()]
        if proc.returncode == 0 and not any("Failed to connect" in ln for ln in err):
            _SYSTEMD_PROBE = (True, "")
        else:
            _SYSTEMD_PROBE = (False, err[0] if err else f"exit {proc.returncode}.")
    except Exception as exc:  # noqa: BLE001 -- any failure means unusable
        _SYSTEMD_PROBE = (False, f"{type(exc).__name__}: {exc}")
    return _SYSTEMD_PROBE


__all__ = ["reset_cache", "systemd_run_works"]
