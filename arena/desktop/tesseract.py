"""Where tesseract is on this machine, and how to write a command line for it (#619)."""
from __future__ import annotations

import os
import shlex
import shutil
from pathlib import Path

# The OCR tools (`ocr.health`, `ocr.extract`) and desktop OCR (`desktop.ocr`,
# `desktop.find_text`, ...) each had their own idea of where tesseract is. The
# first looked on PATH and in the usual install directories; the second looked
# on PATH only and then ran the bare name. On Windows the installer does not
# touch PATH, so one said "ok" and the other "tesseract is not installed" on
# the same machine. Both now ask here.


def candidate_paths() -> list[Path]:
    """Every place tesseract is looked for, in order: PATH first, then the usual install directories."""
    paths: list[Path] = []
    which = shutil.which("tesseract")
    if which:
        paths.append(Path(which))
    home = Path.home()
    for root in [
        home / ".local" / "bin",
        Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Tesseract-OCR",
        Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) / "Tesseract-OCR",
        Path(os.environ.get("LOCALAPPDATA", str(home / "AppData" / "Local"))) / "Programs" / "Tesseract-OCR",
    ]:
        paths.append(root / "tesseract.exe")
    seen: set[str] = set()
    unique = []
    for path in paths:
        key = str(path).lower()
        if key not in seen:
            seen.add(key)
            unique.append(path)
    return unique


def find_tesseract() -> str | None:
    """The tesseract binary to run, or None when there is none."""
    return next((str(path) for path in candidate_paths() if path.is_file()), None)


def tessdata_beside(binary: str) -> str | None:
    """The language data installed next to the binary, which is where the Windows installer puts it."""
    beside = Path(binary).parent / "tessdata"
    return str(beside) if beside.is_dir() else None


def _for_cmd(arg: str) -> str:
    # cmd.exe does not know single quotes, which is what shlex writes. Inside
    # double quotes it takes & | < > ^ and spaces literally. A double quote
    # cannot be passed at all, and no Windows path contains one. Backslashes
    # are literal to the program unless a quote follows them, so only the ones
    # before the closing quote are doubled. `%NAME%` is still expanded by
    # cmd.exe inside quotes; nothing here can prevent that.
    if '"' in arg:
        raise ValueError("an argument with a double quote cannot be passed through cmd.exe")
    trailing = len(arg) - len(arg.rstrip("\\"))
    return '"' + arg + "\\" * trailing + '"'


def command_line(argv: list[str], *, windows: bool | None = None) -> str:
    """One command line for the shell this platform starts: cmd.exe on Windows, sh elsewhere."""
    if windows is None:
        windows = os.name == "nt"
    if windows:
        return " ".join(_for_cmd(arg) for arg in argv)
    return shlex.join(argv)


def tesseract_command(binary: str, image: str, psm: int) -> str:
    """The command that reads `image` and prints TSV, using the language data that came with the binary."""
    argv = [binary, image, "stdout", "--psm", str(int(psm or 11))]
    tessdata = tessdata_beside(binary)
    if tessdata:
        argv += ["--tessdata-dir", tessdata]
    return command_line([*argv, "tsv"])
