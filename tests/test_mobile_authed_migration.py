"""v3.98.0 regression guards: mobile handlers migrated to @authed.

Confirms every module in arena.mobile that used to carry the six-line
require_auth/record/try/except prelude has been migrated to the
shared decorator from arena.handler_helpers, and none of them can
regress via copy-paste of the old shape.
"""
from __future__ import annotations

import inspect
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from arena.mobile import (  # noqa: E402
    handlers as _h,
    handlers_devops as _hd,
    handlers_media as _hm,
    handlers_recording as _hr,
)


def _sources():
    return (_h, _hd, _hm, _hr)


def test_mobile_modules_free_of_manual_auth_prelude():
    """The inline ``r = ctx.require_auth(request); if r: return r``
    prelude is gone from every mobile handler module."""
    for mod in _sources():
        src = inspect.getsource(mod)
        assert "r = ctx.require_auth(request)" not in src, (
            f"{mod.__name__} still contains the inline auth prelude — "
            f"v3.98.0 migrated it to @authed from arena.handler_helpers."
        )


def test_mobile_modules_free_of_manual_error_record():
    """The inline ``ctx.record_request(is_error=True, count_request=False)``
    error-record pattern is gone (the wrapper does it centrally now)."""
    for mod in _sources():
        src = inspect.getsource(mod)
        # Allow the substring inside the shared handler_helpers only —
        # every mobile module should be free of it.
        assert "record_request(is_error=True, count_request=False)" not in src, (
            f"{mod.__name__} still records errors manually — "
            f"@authed does that centrally."
        )


def test_mobile_modules_use_handler_helpers_authed():
    """Every mobile handler module imports @authed."""
    for mod in _sources():
        src = inspect.getsource(mod)
        assert "from arena.handler_helpers import authed" in src or \
               "from arena.handler_helpers import authed, err_json" in src, (
            f"{mod.__name__} does not import authed from arena.handler_helpers."
        )


def test_media_module_no_longer_needs_local_guard_helpers():
    """The pre-v3.98.0 media file carried private ``_guard`` and
    ``_oops`` helpers to reduce boilerplate; with @authed those are
    obsolete."""
    src = inspect.getsource(_hm)
    assert "def _guard(" not in src, (
        "handlers_media still defines the pre-@authed _guard helper — "
        "delete it and rely on @authed."
    )
    assert "def _oops(" not in src, (
        "handlers_media still defines the pre-@authed _oops helper — "
        "delete it and rely on @authed's exception handling."
    )
