"""Desktop handler factory smoke tests."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import unified_bridge as ub  # noqa: E402
from arena.handler_context import DesktopHandlerContext  # noqa: E402
from arena.desktop.handlers import make_desktop_handlers  # noqa: E402


def test_desktop_handlers_factory_outputs():
    ctx = DesktopHandlerContext(
        require_auth=ub.require_auth,
        record_request=ub._record_request,
        cors_json_response=ub._cors_json_response,
        control_check=ub._control_check,
        control_record_agent_action=ub._control_record_agent_action,
        desktop_exec=ub._desktop_exec,
        detect_desktop_env=ub._detect_desktop_env,
        get_active_window=ub._get_active_window,
        kwin_windows_via_script=ub._kwin_windows_via_script,
        capture_screenshot=ub.capture_desktop_screenshot,
        ocr_desktop=ub.ocr_desktop,
        kwin_focus_window=ub.kwin_focus_window_via_script,
        focus_window=ub.focus_window,
        audit=ub.audit,
    )
    handlers = make_desktop_handlers(ctx)
    assert callable(handlers.screenshot)
    assert callable(handlers.displays)
    assert callable(handlers.click)
    assert callable(handlers.type)
    assert callable(handlers.key)
    assert callable(handlers.mouse)
    assert callable(handlers.windows)
    assert callable(handlers.active_window)
    assert callable(handlers.focus)
    assert callable(handlers.ocr)
    assert callable(handlers.find_text)
    assert callable(handlers.click_text)


def test_unified_routes_use_extracted_desktop_handlers():
    app = ub.make_app({"token": "test"})
    paths = {(r.method, r.resource.get_info().get("path") or r.resource.get_info().get("formatter")) for r in app.router.routes()}
    assert ("GET", "/v1/desktop/screenshot") in paths
    assert ("GET", "/v1/desktop/displays") in paths
    assert ("POST", "/v1/desktop/click") in paths
    assert ("POST", "/v1/desktop/type") in paths
    assert ("POST", "/v1/desktop/key") in paths
    assert ("POST", "/v1/desktop/mouse") in paths
    assert ("GET", "/v1/desktop/windows") in paths
    assert ("GET", "/v1/desktop/active_window") in paths
    assert ("POST", "/v1/desktop/focus") in paths
    assert ("POST", "/v1/desktop/ocr") in paths
    assert ("POST", "/v1/desktop/find_text") in paths
    assert ("POST", "/v1/desktop/click_text") in paths


def test_desktop_handlers_facade_uses_split_modules():
    from arena.desktop.display_handler import make_desktop_display_handler
    from arena.desktop.input_handlers import make_desktop_input_handlers
    from arena.desktop.ocr_handler import make_desktop_ocr_handlers
    from arena.desktop.screenshot_handler import make_desktop_screenshot_handler
    from arena.desktop.window_handlers import make_desktop_window_handlers

    assert callable(make_desktop_screenshot_handler)
    assert callable(make_desktop_display_handler)
    assert callable(make_desktop_input_handlers)
    assert callable(make_desktop_window_handlers)
    assert callable(make_desktop_ocr_handlers)
