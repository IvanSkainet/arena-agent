"""#619: desktop OCR and the OCR tools find the same tesseract, and the command for it survives the shell."""
# `ocr.health` said tesseract was at C:/Program Files/Tesseract-OCR/tesseract.exe
# while `POST /v1/desktop/find_text` on the same bridge answered 503 "tesseract
# is not installed": one looked in the install directories, the other on PATH
# only, and then ran the bare name.
from __future__ import annotations

import asyncio
import os
import shutil
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from arena.desktop import ocr, tesseract
from arena.desktop.exec import _desktop_exec
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


def test_a_binary_without_language_data_beside_it_is_left_to_find_its_own(tmp_path, monkeypatch):
    monkeypatch.delenv("TESSDATA_PREFIX", raising=False)
    binary = tmp_path / "bin" / "tesseract"
    binary.parent.mkdir()
    binary.write_bytes(b"")
    command = tesseract.tesseract_command(str(binary), str(tmp_path / "shot.png"), 11)
    assert "--tessdata-dir" not in command


def test_a_directory_beside_the_binary_without_english_is_not_forced_on_tesseract(installed):
    (installed.parent / "tessdata" / "eng.traineddata").rename(installed.parent / "tessdata" / "rus.traineddata")
    assert tesseract.tessdata_beside(str(installed)) is None


@pytest.mark.parametrize("layout", ["", "tessdata"])
def test_language_data_named_by_the_environment_is_not_overridden(installed, tmp_path, monkeypatch, layout):
    """`--tessdata-dir` outranks TESSDATA_PREFIX inside tesseract, so it is not given when the variable works."""
    data = tmp_path / "share" / layout
    data.mkdir(parents=True)
    (data / "eng.traineddata").write_bytes(b"x")
    monkeypatch.setenv("TESSDATA_PREFIX", str(tmp_path / "share"))
    assert tesseract.tessdata_beside(str(installed)) is None
    assert "--tessdata-dir" not in tesseract.tesseract_command(str(installed), "shot.png", 11)


def test_an_environment_that_names_no_data_does_not_hide_the_data_beside_the_binary(installed, tmp_path, monkeypatch):
    monkeypatch.setenv("TESSDATA_PREFIX", str(tmp_path / "nothing-here"))
    assert tesseract.tessdata_beside(str(installed)) == str(installed.parent / "tessdata")


def test_tsv_is_asked_for_by_parameter_not_by_a_config_file_that_may_be_missing(installed):
    """Without `configs/tsv` in the data directory tesseract prints plain text, which reads as "no words"."""
    words = [word.strip("'\"") for word in tesseract.tesseract_command(str(installed), "shot.png", 11).split()]
    assert words[-2:] == ["-c", "tessedit_create_tsv=1"]
    assert "tsv" not in words


@pytest.fixture(name="nowhere")
def _nowhere(tmp_path, monkeypatch):
    """No tesseract on PATH and every install directory pointed at an empty place under `tmp_path`."""
    monkeypatch.setattr(shutil, "which", lambda name: None)
    monkeypatch.setenv("ProgramFiles", str(tmp_path / "pf"))
    monkeypatch.setenv("ProgramFiles(x86)", str(tmp_path / "pf86"))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")
    return tmp_path


@pytest.mark.parametrize("place", ["home/.local/bin/tesseract", "home/.local/bin/tesseract.exe",
                                   "pf/Tesseract-OCR/tesseract.exe", "pf86/Tesseract-OCR/tesseract.exe",
                                   "local/Programs/Tesseract-OCR/tesseract.exe"])
def test_every_install_directory_is_looked_in(nowhere, place):
    """The user's own bin directory under both names, and the three places the Windows installers use."""
    assert tesseract.find_tesseract() is None
    binary = nowhere.joinpath(*place.split("/"))
    binary.parent.mkdir(parents=True)
    binary.write_bytes(b"")
    assert tesseract.find_tesseract() == str(binary)


def test_the_usual_directories_are_assumed_when_the_environment_does_not_name_them(nowhere, monkeypatch):
    for name in ("ProgramFiles", "ProgramFiles(x86)", "LOCALAPPDATA"):
        monkeypatch.delenv(name)
    assert tesseract.candidate_paths()[2:] == [
        Path(r"C:\Program Files") / "Tesseract-OCR" / "tesseract.exe",
        Path(r"C:\Program Files (x86)") / "Tesseract-OCR" / "tesseract.exe",
        nowhere / "home" / "AppData" / "Local" / "Programs" / "Tesseract-OCR" / "tesseract.exe",
    ]


def test_a_blank_data_variable_does_not_mean_the_current_directory(installed, tmp_path, monkeypatch):
    (tmp_path / "eng.traineddata").write_bytes(b"x")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("TESSDATA_PREFIX", "  ")
    assert tesseract.tessdata_beside(str(installed)) == str(installed.parent / "tessdata")


@pytest.mark.parametrize(("asked", "written"), [(0, "11"), (None, "11"), (6, "6"), (11, "11")])
def test_the_page_segmentation_mode_is_the_one_asked_for_or_sparse_text(asked, written):
    words = tesseract.tesseract_command("tesseract", "shot.png", asked).split()
    assert [word.strip('"') for word in words[2:5]] == ["stdout", "--psm", written]


@pytest.mark.parametrize(("platform", "line"), [("nt", '"a b"'), ("posix", "'a b'")])
def test_the_shell_is_chosen_by_the_platform_when_the_caller_does_not_say(monkeypatch, platform, line):
    monkeypatch.setattr(tesseract, "os", SimpleNamespace(name=platform))
    assert tesseract.command_line(["a b"]) == line


_STAND_IN = """import pathlib, sys
if not pathlib.Path(sys.argv[1]).is_file():
    sys.exit("no such image: %r" % sys.argv[1:])
if sys.argv[2:] != ["stdout", "--psm", "11", "--tessdata-dir", sys.argv[-3], "-c", "tessedit_create_tsv=1"]:
    sys.exit("unexpected arguments: %r" % sys.argv[1:])
if not (pathlib.Path(sys.argv[-3]) / "eng.traineddata").is_file():
    sys.exit("no data in %r" % sys.argv[-3])
sys.stdout.write(TSV)
"""


def _stand_in_program(directory: Path) -> Path:
    """A program the platform can start by path, in a directory with a space, that checks what it is given."""
    script = directory / "stand_in.py"
    script.write_text(f"TSV = {_TSV!r}\n{_STAND_IN}", encoding="utf-8")
    if os.name == "nt":
        program = directory / "tesseract.cmd"
        program.write_text(f'@"{sys.executable}" "%~dp0stand_in.py" %*\r\n', encoding="utf-8")
        return program
    program = directory / "tesseract"
    program.write_text(f"#!{sys.executable}\nimport runpy\nrunpy.run_path({str(script)!r}, run_name='__main__')\n",
                       encoding="utf-8")
    program.chmod(0o755)
    return program


def test_the_command_desktop_ocr_writes_is_one_the_platform_shell_runs(installed, monkeypatch):
    """The whole path with nothing faked but tesseract: real temp image, real shell, a program that checks its arguments."""
    program = _stand_in_program(installed.parent)
    monkeypatch.setattr(ocr, "find_tesseract", lambda: str(program))

    async def capture(**_kwargs):
        return {"ok": True, "bytes": b"png", "encoding": "png", "tool": "fake", "transformed": False}

    result = asyncio.run(ocr.ocr_desktop(query="Arena", capture_screenshot=capture, desktop_exec=_desktop_exec,
                                         detect_env=lambda: {}))
    assert result["ok"] is True, result
    assert result["best_match"]["text"] == "Arena"


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
    assert tesseract.command_line(["C:\\XX\\\\"], windows=True) == '"C:\\XX\\\\\\\\"'
    assert tesseract.command_line(["C:\\XX"], windows=True) == '"C:\\XX"'


def test_a_percent_sign_is_kept_from_cmd_which_expands_names_inside_quotes_too():
    assert tesseract.command_line([r"C:\Users\50%OS%\shot.png"], windows=True) == r'"C:\Users\50"^%"OS"^%"\shot.png"'
    assert tesseract.command_line(["%"], windows=True) == "^%"
    assert tesseract.command_line(["dir\\%TEMP%"], windows=True) == '"dir\\\\"^%"TEMP"^%'


def test_an_empty_argument_stays_an_argument():
    assert tesseract.command_line(["a", ""], windows=True) == '"a" ""'


def test_a_double_quote_is_refused_for_cmd_rather_than_passed_on_broken():
    with pytest.raises(ValueError, match=r"^an argument with a double quote cannot be passed through cmd\.exe$"):
        tesseract.command_line(['a"b'], windows=True)


def test_elsewhere_the_command_line_is_written_for_sh():
    assert tesseract.command_line(["/usr/bin/tesseract", "/shots/a b.png", "tsv"], windows=False) == \
        "/usr/bin/tesseract '/shots/a b.png' tsv"


@pytest.mark.parametrize("argument", ["plain", "two words", "a&b", "semi;colon", "pipe|d", "(parens)", "a^b",
                                      "it's", "tail\\", "C:\\Program Files\\x y\\z.png", "%PATH%", "%OS%",
                                      "50%", "%", "a%PATH%b c", "dir\\%PATH%\\", "%PATH:~0,3%", ""])
def test_every_argument_comes_out_of_the_real_shell_as_it_went_in(argument):
    """Through the runner desktop OCR uses, so through the shell this platform really starts."""
    line = tesseract.command_line([sys.executable, "-c", "import sys; sys.stdout.write(sys.argv[1])", argument])
    done = asyncio.run(_desktop_exec(line, timeout=30))
    assert done["ok"] is True, done
    assert done["stdout"] == argument
