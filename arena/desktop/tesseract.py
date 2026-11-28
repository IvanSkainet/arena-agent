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


def _has_english(directory: Path) -> bool:
    return (directory / "eng.traineddata").is_file()


def _environment_names_data() -> bool:
    # TESSDATA_PREFIX is the data directory itself for tesseract 4 and 5, and its parent for 3.
    prefix = os.environ.get("TESSDATA_PREFIX")
    if prefix is None or not prefix.strip():
        return False
    named = Path(prefix.strip()).expanduser()
    return _has_english(named) or _has_english(named / "tessdata")


def tessdata_beside(binary: str) -> str | None:
    """The language data next to the binary when it has to be named, else None: tesseract finds its own."""
    # `--tessdata-dir` outranks TESSDATA_PREFIX inside tesseract. So it is given
    # only when the environment does not already point at usable data, and only
    # for a directory that has the language desktop OCR reads.
    if _environment_names_data():
        return None
    beside = Path(binary).parent / "tessdata"
    return str(beside) if _has_english(beside) else None


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
    """The command that reads `image` and prints TSV, using the language data that came with the binary."""
    argv = [binary, image, "stdout", "--psm", str(int(psm or 11))]
    tessdata = tessdata_beside(binary)
    if tessdata:
        argv += ["--tessdata-dir", tessdata]
    # The parameter, not the `tsv` config file: the file is looked for in the
    # data directory, and where it is missing tesseract prints plain text,
    # which the TSV reader takes for "no words on screen".
    return command_line(argv + list(TSV_OUTPUT))
