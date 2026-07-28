"""v4.106.0 -- BrowserAct browse backend uses run.py, not bash/run.sh."""
from __future__ import annotations

import inspect
from pathlib import Path

import arena.browser.browse_browseract as mod


def test_browseract_backend_uses_cross_platform_python_wrapper():
    src = inspect.getsource(mod.run_browseract_browse)
    assert 'run.py' in src
    assert 'sys.executable' in src
    assert ' / \"run.sh\"' not in src
    assert 'shutil.which(\"bash\")' not in src
