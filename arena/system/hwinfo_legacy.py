"""Legacy extended hardware info collector used as inventory fallback."""
from __future__ import annotations

import platform

from arena.system.hwinfo_common import empty_hwinfo
from arena.system.hwinfo_linux import fill_linux_hwinfo
from arena.system.hwinfo_windows import fill_windows_hwinfo


def collect_legacy_hwinfo(*, subprocess_kwargs_fn):
    """Collect extended hardware info. Cross-platform."""
    info = empty_hwinfo()
    system = platform.system()
    if system == "Windows":
        return fill_windows_hwinfo(info, subprocess_kwargs_fn=subprocess_kwargs_fn)
    if system == "Linux":
        return fill_linux_hwinfo(info, subprocess_kwargs_fn=subprocess_kwargs_fn)
    return info
