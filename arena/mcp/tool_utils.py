"""Shared MCP tool execution/response helpers."""
from __future__ import annotations

import os
import platform
import subprocess
from collections.abc import Callable
from typing import Any

# Decoding options for children we know print UTF-8: our own helper scripts,
# which force it on their side (see `bin/py_browser.py` and #127).
#
# Opt-in per call, never a default. The same runners also carry `exec.run`,
# i.e. arbitrary Windows commands whose output really is in the OEM codepage;
# pinning utf-8 there would fix the browser and corrupt everything else --
# `Каталог` in cp866 comes back as replacement characters. Only the call
# sites that launch a script of ours may ask for it.
UTF8_CHILD_IO: dict[str, str] = {"encoding": "utf-8", "errors": "replace"}


def _decoding(utf8_child: bool, base: dict[str, Any]) -> dict[str, Any]:
    """Merge the caller's subprocess kwargs with the UTF-8 opt-in.

    Merged into one dict rather than unpacked twice: `f(**a, **b)` raises
    TypeError the moment both carry `encoding`, and `subprocess_kwargs` is
    free to set one. An explicit caller value wins over ours.
    """
    if not utf8_child:
        return dict(base)
    return {**UTF8_CHILD_IO, **base}


def make_run_local(subprocess_kwargs: Callable[[], dict[str, Any]]):
    def run_local(argv: list[str], timeout: int = 30, *, utf8_child: bool = False) -> tuple[int, str, str]:
        """Run a command directly (no GUI/sandbox needed).

        `utf8_child` is for our own helper scripts only; see UTF8_CHILD_IO.
        """
        p = subprocess.run(argv, capture_output=True, text=True, timeout=timeout,
                           **_decoding(utf8_child, subprocess_kwargs()))
        return p.returncode, p.stdout, p.stderr

    return run_local


def make_run_sd(*, bin_dir: Any, subprocess_kwargs: Callable[[], dict[str, Any]]):
    def run_sd(argv: list[str], timeout: int = 60) -> tuple[int, str, str]:
        """Run command via sd-exec (Linux) or directly (Windows).

        No `shell=True` on the Windows branch. It was there with a `nosec`
        claiming "argv[0] is a fixed sd-exec binary path (no operator
        interpolation)", and that claim was simply untrue: every Windows
        caller passes attacker-influenced argv -- `browser.shot` appends a
        URL, `exec.run` appends the operator's command line.

        With `shell=True`, Python joins the list with `list2cmdline` and
        hands the single string to `cmd.exe`, which then re-reads it for
        `&`, `|`, `>`. `list2cmdline` quotes for the *C runtime*, not for
        the shell, and it only quotes arguments containing spaces -- so a
        URL like `http://x/?a=1&echo.PWNED>C:/tmp/m.txt` carries no space,
        gets no quotes, and `cmd` runs the tail as a second command.
        Verified on the operator's Windows 3.14.7 host: the marker file was
        created with `shell=True` and was not created with it removed.

        Dropping it changes nothing else. The same call without a shell
        runs the same programs, and actually returns cleaner output: with
        `shell=True`, `cmd /c echo hello` came back as `hello"`.
        """
        if platform.system() == "Windows":
            p = subprocess.run(argv, capture_output=True, text=True, timeout=timeout, **subprocess_kwargs())
            return p.returncode, p.stdout, p.stderr
        sd = os.path.join(bin_dir, "sd-exec")
        p = subprocess.run([sd, "--timeout", str(timeout), "--"] + argv,
                           capture_output=True, text=True, timeout=timeout + 10, **subprocess_kwargs())
        return p.returncode, p.stdout, p.stderr

    return run_sd


def text_content(s: str) -> dict:
    return {"content": [{"type": "text", "text": s}]}
