"""v4.42.0 test that mobile UI XML parsing rejects DOCTYPE /
entity declarations before they reach the (billion-laughs
vulnerable) stdlib XML parser.
"""
from __future__ import annotations

import inspect

import pytest

from arena.mobile import ui


def test_ui_module_gates_doctype_before_fromstring():
    """Regression guard: the "<!doctype/entity substring check
    must appear before the ET.fromstring call. A refactor that
    reorders those two lines would silently reintroduce the
    billion-laughs risk."""
    src = inspect.getsource(ui)
    doctype_pos = src.lower().find("<!doctype")
    fromstring_pos = src.find("ET.fromstring")
    assert doctype_pos != -1, "DOCTYPE gate check missing"
    assert fromstring_pos != -1, "ET.fromstring call missing"
    assert doctype_pos < fromstring_pos, (
        "the <!doctype substring check must come BEFORE ET.fromstring "
        "so a malicious dump cannot reach the vulnerable parser"
    )


# Direct behavioural test of the gate. We stub the adb call so
# the rest of dump_ui runs but returns our chosen XML.
class _StubAdbResult:
    def __init__(self, raw):
        self.stdout = raw
        self.stderr = b""
        self.returncode = 0


@pytest.fixture
def stub_adb(monkeypatch):
    """Force ``find_adb()`` to return a truthy path and stub
    ``run()`` so ``dump_ui`` runs its parser branch instead of
    early-returning "adb not installed"."""
    from arena.mobile import adb
    monkeypatch.setattr(ui, "find_adb", lambda: "/usr/bin/adb")

    captured_xml = {"value": ""}

    def _fake_run(*args, **kwargs):
        raw = captured_xml["value"]
        return type("R", (), {
            "returncode": 0,
            "stdout": raw.encode() if isinstance(raw, str) else raw,
            "stderr": b"",
        })()

    monkeypatch.setattr(ui, "run", _fake_run)
    return captured_xml


BILLION_LAUGHS = """<?xml version="1.0"?>
<!DOCTYPE lolz [
  <!ENTITY lol "lol">
  <!ENTITY lol2 "&lol;&lol;&lol;&lol;&lol;">
  <!ENTITY lol3 "&lol2;&lol2;&lol2;&lol2;&lol2;">
  <!ENTITY lol4 "&lol3;&lol3;&lol3;&lol3;&lol3;">
]>
<hierarchy><lolz>&lol4;</lolz></hierarchy>"""


EXTERNAL_ENTITY = """<?xml version="1.0"?>
<!DOCTYPE foo [<!ENTITY xxe SYSTEM "file:///etc/passwd">]>
<hierarchy>&xxe;</hierarchy>"""


def test_dump_ui_rejects_billion_laughs(stub_adb):
    stub_adb["value"] = BILLION_LAUGHS
    result = ui.dump_ui("emu-1234")
    assert result["ok"] is False
    assert "DOCTYPE" in result["error"] or "entity" in result["error"].lower()


def test_dump_ui_rejects_external_entity(stub_adb):
    stub_adb["value"] = EXTERNAL_ENTITY
    result = ui.dump_ui("emu-1234")
    assert result["ok"] is False
    assert "DOCTYPE" in result["error"] or "entity" in result["error"].lower()


def test_dump_ui_accepts_ordinary_hierarchy(stub_adb):
    """Positive control: a legitimate uiautomator dump must
    still parse fine after v4.42.0. Otherwise the gate has
    over-shot and broken every mobile UI call."""
    stub_adb["value"] = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<hierarchy rotation="0">'
        '<node index="0" text="" resource-id="" class="android.view.View" '
        'package="com.example" content-desc="" bounds="[0,0][1080,2400]"/>'
        '</hierarchy>'
    )
    result = ui.dump_ui("emu-1234")
    # ok may be True or False depending on other checks (screen bounds
    # etc.), but critically it must NOT be a "DOCTYPE not allowed" rejection.
    if not result.get("ok"):
        assert "DOCTYPE" not in result.get("error", "")
