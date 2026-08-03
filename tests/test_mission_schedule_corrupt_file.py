"""Gate: a corrupt schedule file must not turn an update into a crash.

`_load()` returns None for unreadable/invalid JSON. The original guard in
`save_schedule_def` was `if current and not isinstance(current, dict)`, which
short-circuits on the falsy None and left `current = None`; every
`current.get(...)` in the schedule dict below then raised AttributeError.
Found by pyrefly (14x "Object of class NoneType has no attribute get").
"""
from __future__ import annotations

import json

from arena.resources.mission_schedule_store import (
    _load,
    list_schedule_defs,
    save_schedule_def,
)


def _payload() -> dict:
    return {"mission_id": "m1", "action": "iterate", "schedule_id": "s1"}


def test_save_over_invalid_json_rewrites_instead_of_raising(tmp_path):
    (tmp_path / "s1.json").write_text("{not json", encoding="utf-8")
    out = save_schedule_def(tmp_path, _payload())
    assert out["ok"] is True
    assert out["schedule"]["mission_id"] == "m1"
    assert json.loads((tmp_path / "s1.json").read_text(encoding="utf-8"))["id"] == "s1"


def test_save_over_non_dict_json_rewrites_instead_of_raising(tmp_path):
    (tmp_path / "s1.json").write_text("[1, 2, 3]", encoding="utf-8")
    out = save_schedule_def(tmp_path, _payload())
    assert out["ok"] is True
    assert out["schedule"]["every_minutes"] == 60


def test_load_rejects_non_dict_payloads(tmp_path):
    p = tmp_path / "x.json"
    for raw in ("[1]", '"str"', "12", "null"):
        p.write_text(raw, encoding="utf-8")
        assert _load(p) is None


def test_existing_schedule_fields_are_still_preserved(tmp_path):
    save_schedule_def(tmp_path, {**_payload(), "notes": "keep-me"})
    save_schedule_def(tmp_path, _payload())
    got = list_schedule_defs(tmp_path)
    assert len(got) == 1 and got[0]["notes"] == "keep-me"
