"""Execute the actual shipped sd-exec resource with the artifact interpreter."""
import json
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_sd_exec_scope_contract_from_selected_artifact(tmp_path):
    command = json.loads(os.environ.get("ARENA_E2E_SERVER_CMD", "[]"))
    executable = command[0] if command else sys.executable
    # Installed mode must not inject the checkout on sys.path. Source mode
    # explicitly supplies it because this test also runs in the normal suite.
    source = "" if command else str(REPO_ROOT)
    program = r'''
import importlib.machinery, importlib.util, os, sys
from types import SimpleNamespace
if sys.argv[1]:
    sys.path.insert(0, sys.argv[1])
from arena.home import executable_root
resource = executable_root() / "bin" / "sd-exec"
assert resource.is_file(), resource
if not sys.argv[1]:
    assert "_executables" in resource.parts, resource
if os.name != "nt":
    assert os.access(resource, os.X_OK), resource
loader = importlib.machinery.SourceFileLoader("artifact_sd_exec", str(resource))
spec = importlib.util.spec_from_loader(loader.name, loader)
assert spec is not None
module = importlib.util.module_from_spec(spec)
loader.exec_module(module)
calls = []
module._build_env_flags = lambda: []
module.subprocess.run = lambda argv, **kwargs: calls.append(argv) or SimpleNamespace(returncode=0)
assert module._run_systemd({"no_pipe":False,"timeout":None,"background":False}, ["echo","safe"]) == 0
assert "--scope" in calls[0], calls
assert "--pipe" not in calls[0], calls
print(resource)
'''
    result = subprocess.run([executable, "-I", "-c", program, source], cwd=tmp_path,
                            capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, (result.stdout, result.stderr)
