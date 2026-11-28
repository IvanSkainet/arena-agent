"""#619: desktop OCR and the OCR tools find the same tesseract, and the command for it survives the shell.

`ocr.health` said tesseract was at `C:\\Program Files\\Tesseract-OCR\\tesseract.exe`
while `POST /v1/desktop/find_text` on the same bridge answered 503 "tesseract
is not installed": one looked in the install directories, the other on PATH
only, and then ran the bare name.
"""
from __future__ import annotations

import asyncio
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from arena.desktop import ocr, tesseract
from arena.mcp import tool_ocr

_TSV = "level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext\n" \
       "5\t1\t1\t1\t1\t1\t10\t10\t50\t20\t95\tArena\n"


@pytest.fixture(name="installed")
def _installed(tmp_path, monkeypatch):
    """A tesseract in the Windows install directory and nowhere on PATH, with its language data beside it."""
    root = tmp_path / "Program Files" / "Tesseract-OCR"
    (root / "tessdata").mkdir(parents=True)
    (root / "tessdata" / "eng.traineddata").write_bytes(b"x")
    binary = root / "tesseract.exe"
    binary.write_bytes(b"")
    monkeypatch.setattr(shutil, "which", lambda name: None)
    monkeypatch.setenv("ProgramFiles", str(tmp_path / "Program Files"))
    monkeypatch.setenv("ProgramFiles(x86)", str(tmp_path / "none-x86"))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "none-local"))
    monkeypatch.delenv("TESSDATA_PREFIX", raising=False)
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")
    return binary


def _read_screen(commands: list[str]) -> dict:
    async def capture(**_kwargs):
        return {"ok": True, "bytes": b"png", "encoding": "png", "tool": "fake", "transformed": False}

    async def run(cmd: str, timeout: float = 10):
        commands.append(cmd)
        return {"ok": True, "stdout": _TSV, "stderr": ""}

    return asyncio.run(ocr.ocr_desktop(query="Arena", capture_screenshot=capture, desktop_exec=run,
                                       detect_env=lambda: {}))


def test_an_install_that_is_not_on_path_is_found(installed):
    assert tesseract.find_tesseract() == str(installed)


def test_desktop_ocr_and_the_ocr_tools_name_the_same_binary(installed):
    """The pair from the Issue: what `ocr.health` reports is what desktop OCR runs."""
    commands: list[str] = []
    result = _read_screen(commands)
    health = tool_ocr._handle_ocr_health({})
    assert health["tesseract"] == str(installed)
    assert result["ok"] is True, result
    assert len(commands) == 1
    assert str(installed) in commands[0]
    assert result["best_match"]["text"] == "Arena"


def test_desktop_ocr_uses_the_language_data_that_came_with_the_binary(installed):
    commands: list[str] = []
    _read_screen(commands)
    assert "--tessdata-dir" in commands[0]
    assert str(installed.parent / "tessdata") in commands[0]


def test_a_binary_without_language_data_beside_it_is_left_to_find_its_own(tmp_path):
    binary = tmp_path / "bin" / "tesseract"
    binary.parent.mkdir()
    binary.write_bytes(b"")
    command = tesseract.tesseract_command(str(binary), str(tmp_path / "shot.png"), 11)
    assert "--tessdata-dir" not in command
    assert command.endswith(" tsv")


def test_path_is_asked_first(installed, tmp_path, monkeypatch):
    on_path = tmp_path / "bin" / "tesseract"
    on_path.parent.mkdir()
    on_path.write_bytes(b"")
    monkeypatch.setattr(shutil, "which", lambda name: str(on_path) if name == "tesseract" else None)
    assert tesseract.find_tesseract() == str(on_path)
    assert tesseract.candidate_paths()[0] == on_path
    assert installed in tesseract.candidate_paths()


def test_no_tesseract_anywhere_is_still_the_marked_refusal(tmp_path, monkeypatch):
    """Nothing is run, and the answer keeps the `unavailable` list that makes it a 503 (#260)."""
    monkeypatch.setattr(shutil, "which", lambda name: None)
    for name in ("ProgramFiles", "ProgramFiles(x86)", "LOCALAPPDATA"):
        monkeypatch.setenv(name, str(tmp_path / "none"))
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")
    commands: list[str] = []
    result = _read_screen(commands)
    assert tesseract.find_tesseract() is None
    assert result == {"ok": False, "error": "tesseract is not installed", "unavailable": ["tesseract"]}
    assert commands == []


def test_the_same_place_is_listed_once(tmp_path, monkeypatch):
    monkeypatch.setattr(shutil, "which", lambda name: None)
    for name in ("ProgramFiles", "ProgramFiles(x86)", "LOCALAPPDATA"):
        monkeypatch.setenv(name, str(tmp_path / "Same"))
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")
    places = [str(path).lower() for path in tesseract.candidate_paths()]
    assert len(places) == len(set(places))


def test_a_windows_command_line_is_written_for_cmd_not_for_sh():
    r"""`shlex.quote` wrote 'C:\...\shot.png' in single quotes, which cmd.exe passes on as part of the name."""
    line = tesseract.command_line(
        [r"C:\Program Files\Tesseract-OCR\tesseract.exe", r"C:\Users\Tom&Jerry\Temp\shot.png", "stdout"], windows=True)
    assert line == r'"C:\Program Files\Tesseract-OCR\tesseract.exe" "C:\Users\Tom&Jerry\Temp\shot.png" "stdout"'
    assert "'" not in line


def test_a_trailing_backslash_does_not_swallow_the_closing_quote():
    assert tesseract.command_line(["C:\\data\\"], windows=True) == '"C:\\data\\\\"'


def test_a_double_quote_is_refused_for_cmd_rather_than_passed_on_broken():
    with pytest.raises(ValueError, match="double quote"):
        tesseract.command_line(['a"b'], windows=True)


def test_elsewhere_the_command_line_is_written_for_sh():
    assert tesseract.command_line(["/usr/bin/tesseract", "/tmp/a b.png", "tsv"], windows=False) == \
        "/usr/bin/tesseract '/tmp/a b.png' tsv"


@pytest.mark.parametrize("argument", ["plain", "two words", "a&b", "semi;colon", "pipe|d", "(parens)", "a^b",
                                      "it's", "tail\\", "C:\\Program Files\\x y\\z.png"])
def test_every_argument_comes_out_of_the_real_shell_as_it_went_in(argument):
    """Through the shell this platform really starts: cmd.exe on Windows, sh elsewhere."""
    line = tesseract.command_line([sys.executable, "-c", "import sys; sys.stdout.write(sys.argv[1])", argument])
    done = subprocess.run(line, shell=True, capture_output=True, text=True, timeout=30, check=False)  # noqa: S602
    assert done.returncode == 0, done.stderr
    assert done.stdout == argument
