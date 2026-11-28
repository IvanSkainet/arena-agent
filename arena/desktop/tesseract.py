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

TSV_OUTPUT = ("-c", "tessedit_create_tsv=1")


def candidate_paths() -> list[Path]:
    """Every place tesseract is looked for, in order: PATH first, then the usual install directories."""
    paths: list[Path] = []
    which = shutil.which("tesseract")
    if which:
        paths.append(Path(which))
    home = Path.home()
    paths.append(home / ".local" / "bin" / "tesseract")
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


def _quoted(piece: str) -> str:
    # Backslashes are literal to the program unless a quote follows them, so
    # only the ones before the closing quote are doubled.
    trailing = len(piece) - len(piece.rstrip("\\"))
    return '"' + piece + "\\" * trailing + '"' if piece else ""


def _for_cmd(arg: str) -> str:
    # cmd.exe does not know single quotes, which is what shlex writes. Inside
    # double quotes it takes & | < > ^ and spaces literally. A double quote
    # cannot be passed at all, and no Windows path contains one.
    #
    # `%NAME%` is expanded before quotes are looked at, inside them too. So a
    # percent sign is written outside the quotes as `^%`: the name cmd.exe then
    # looks up ends in a caret, no such variable exists, the text is left as it
    # is, and the caret is dropped on the next pass.
    if '"' in arg:
        raise ValueError("an argument with a double quote cannot be passed through cmd.exe")
    return "^%".join(_quoted(piece) for piece in arg.split("%")) or '""'


def command_line(argv: list[str], *, windows: bool | None = None) -> str:
    """One command line for the shell this platform starts: cmd.exe on Windows, sh elsewhere."""
    if windows is None:
        windows = os.name == "nt"
    if windows:
        return " ".join(_for_cmd(arg) for arg in argv)
    return shlex.join(argv)


def tesseract_command(binary: str, image: str, psm: int) -> str:
    """The command that reads `image` and prints TSV."""
    # No `--tessdata-dir`: it outranks TESSDATA_PREFIX inside tesseract, and
    # what that variable means differs between tesseract 3 and 4. A tesseract
    # installed beside its data finds it without being told (checked with the
    # Windows build, 5.4), so the language data is left to tesseract, as it
    # was before #619.
    #
    # TSV by parameter, not by the `tsv` config file: the file is looked for in
    # the data directory, and where it is missing tesseract exits 0 and prints
    # plain text, which the TSV reader takes for "no words on screen".
    return command_line([binary, image, "stdout", "--psm", str(int(psm or 11))] + list(TSV_OUTPUT))
