"""The documented smoke commands must work outside the data directory."""
import os
import re
import subprocess
from pathlib import Path

import pytest

DOC = Path(__file__).resolve().parents[1] / "AGENTS.md"


def _example():
    text = DOC.read_text(encoding="utf-8")
    section = text.split("For remote-access / provider work", 1)[1]
    return re.search(r"```bash\n(.*?)\n```", section, re.DOTALL).group(1)


def test_remote_example_does_not_use_a_relative_token_path():
    assert "cat token.txt" not in _example()
    assert 'cat "$TOKEN_PATH"' in _example()


@pytest.mark.skipif(os.name == "nt", reason="the documented example is a Bash script")
@pytest.mark.parametrize("location", ["default", "agent_home", "explicit"])
def test_smoke_example_uses_the_configured_token_from_any_cwd(tmp_path, location):
    home = tmp_path / "home"
    work = tmp_path / "checkout"
    bindir = tmp_path / "bin"
    for directory in (home, work, bindir):
        directory.mkdir()
    env = os.environ.copy()
    env.update({"HOME": str(home), "PATH": str(bindir) + os.pathsep + env["PATH"]})
    for key in ("ARENA_TOKEN_FILE", "ARENA_AGENT_HOME"):
        env.pop(key, None)
    if location == "agent_home":
        token_path = tmp_path / "custom-state" / "token.txt"
        env["ARENA_AGENT_HOME"] = str(token_path.parent)
    elif location == "explicit":
        token_path = tmp_path / "credentials" / "bridge-token"
        env["ARENA_TOKEN_FILE"] = str(token_path)
    else:
        token_path = home / "arena-bridge" / "token.txt"
    token_path.parent.mkdir()
    token_path.write_text("example-secret")
    for name, code in (("curl", "#!/bin/sh\nprintf '%s\\n' \"$@\"\n"),
                       ("jq", "#!/bin/sh\ncat\n")):
        script = bindir / name
        script.write_text(code)
        script.chmod(0o755)
    result = subprocess.run(["bash", "-c", _example()], cwd=work, env=env,
                            capture_output=True, text=True, check=True)
    assert result.stdout.count("Authorization: Bearer example-secret") == 2
    assert "Token file is not readable" not in result.stderr


@pytest.mark.skipif(os.name == "nt", reason="the documented example is a Bash script")
def test_smoke_example_reports_missing_token_without_calling_curl(tmp_path):
    env = os.environ.copy()
    env.update({"HOME": str(tmp_path), "ARENA_TOKEN_FILE": str(tmp_path / "missing")})
    result = subprocess.run(["bash", "-c", _example()], cwd=tmp_path, env=env,
                            capture_output=True, text=True, check=True)
    assert "Token file is not readable" in result.stderr
    assert not result.stdout


@pytest.mark.skipif(os.name == "nt", reason="the documented example is a Bash script")
def test_smoke_example_reports_empty_token_without_calling_curl(tmp_path):
    token = tmp_path / "empty-token"
    token.write_text("")
    env = os.environ.copy()
    env["ARENA_TOKEN_FILE"] = str(token)
    result = subprocess.run(["bash", "-c", _example()], cwd=tmp_path, env=env,
                            capture_output=True, text=True, check=True)
    assert "Token file is empty" in result.stderr
    assert not result.stdout
