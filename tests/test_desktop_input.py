"""Desktop input command builder tests."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from arena.desktop.input import build_click_command, build_key_command, build_mouse_command, build_type_command  # noqa: E402
import unified_bridge as ub  # noqa: E402


def test_click_builder_ydotool():
    cmd, tool, err = build_click_command(env={"has_ydotool": True}, x=10, y=20, button="left")
    assert err is None
    assert tool == "ydotool"
    assert "mousemove --absolute 10 20" in cmd
    assert "ydotool click" in cmd


def test_type_builder_xdotool():
    cmd, tool, err = build_type_command(env={"has_xdotool": True}, text="hello world", delay=10, clear=True)
    assert err is None
    assert tool == "xdotool"
    assert "ctrl+a" in cmd
    assert "hello world" in cmd


def test_key_builder_combo():
    cmd, tool, err, label = build_key_command(env={"has_ydotool": True}, key="ctrl+a")
    assert err is None
    assert tool == "ydotool"
    assert label == "ctrl+a"
    assert "29:1" in cmd and "29:0" in cmd


def test_mouse_builder_no_tool():
    cmd, tool, err = build_mouse_command(env={}, x=1, y=2)
    assert cmd is None
    assert tool == "none"
    assert "No mouse tool" in err


def test_unified_bridge_reexports_input_builders():
    assert ub.build_click_command is build_click_command
    assert ub.build_type_command is build_type_command
