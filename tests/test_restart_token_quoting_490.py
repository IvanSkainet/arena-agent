"""Custom restart token paths stay data for both shell template families."""
import os
import subprocess
from dataclasses import replace

import pytest

from arena.service.restart_common import RestartContext, render_template

CTX = RestartContext(8765, "Linux", "/unused/bridge.py", "/unused/token", "Arena", 999)


@pytest.mark.skipif(os.name == "nt", reason="POSIX shell quoting")
def test_posix_restart_token_path_cannot_execute_shell_fragments(tmp_path):
    token = tmp_path / "token ' \" $(touch INJECTED) &.txt"
    token.write_text("expected")
    script = render_template('test -f "__TOKEN_FILE__" && cat \'__TOKEN_FILE__\'',
                             replace(CTX, token_file=str(token)))
    result = subprocess.run(["bash", "-c", script], cwd=tmp_path, capture_output=True, text=True, check=True)
    assert result.stdout == "expected"
    assert not (tmp_path / "INJECTED").exists()


def test_windows_restart_escapes_percent_and_disables_delayed_expansion():
    script = render_template('if exist "__TOKEN_FILE__" echo found',
                             replace(CTX, sys_name="Windows", token_file=r'C:\tokens\%PATH% ! &.txt'))
    assert "setlocal DisableDelayedExpansion" in script
    assert r'C:\tokens\%%PATH%% ! &.txt' in script
    assert 'if exist "%ARENA_RESTART_TOKEN_FILE%"' in script


@pytest.mark.parametrize("path", ['C:\\bad"path', "bad\npath", "bad\rpath", "bad\0path"])
def test_windows_restart_refuses_impossible_token_paths(path):
    with pytest.raises(ValueError, match="invalid Windows"):
        render_template("__TOKEN_FILE__", replace(CTX, sys_name="Windows", token_file=path))
