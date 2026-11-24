"""Bridge logging bootstrap helpers."""
from __future__ import annotations

import contextlib
import logging
import logging.handlers
import os
import sys
from pathlib import Path

from arena.private_state import private_directory


class OwnerOnlyRotatingFileHandler(logging.handlers.RotatingFileHandler):
    """A rotating log that only its owner can read, the rotated copies included."""

    def _open(self):
        # Runs for the first file and again after every rollover. A bare chmod,
        # not `fileperms.restrict`: that one logs its failures, and a log call
        # made while this handler is reopening its own file would come back here.
        stream = super()._open()
        with contextlib.suppress(OSError, NotImplementedError):
            os.chmod(self.baseFilename, 0o600)
        return stream

    def rotate(self, source, dest):
        # Some filesystems reset the mode across a rename.
        super().rotate(source, dest)
        with contextlib.suppress(OSError, NotImplementedError):
            os.chmod(dest, 0o600)


def setup_logging(*, app_dir: Path, log_file: Path | None = None) -> logging.Logger:
    """Configure structured logging with file rotation and console output."""
    logger = logging.getLogger("arena-bridge")
    logger.setLevel(logging.DEBUG)

    if logger.handlers:
        return logger

    fmt = logging.Formatter(
        "%(asctime)s %(levelname)-5s [%(name)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    ch = logging.StreamHandler(sys.stderr)
    ch.setLevel(logging.INFO)
    ch.setFormatter(fmt)
    logger.addHandler(ch)

    try:
        # The log sits beside the audit log (#521), which keeps this directory
        # private; logging starts first, so it has to arrive private already.
        try:
            private_directory(app_dir)
        except OSError:
            app_dir.mkdir(parents=True, exist_ok=True)
        fh = OwnerOnlyRotatingFileHandler(
            str(log_file or (app_dir / "bridge.log")),
            maxBytes=5 * 1024 * 1024,
            backupCount=5,
            encoding="utf-8",
        )
        fh.setLevel(logging.DEBUG)
        fh.setFormatter(fmt)
        logger.addHandler(fh)
    except Exception:
        pass

    return logger
