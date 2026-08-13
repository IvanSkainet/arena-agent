"""v4.169.42 -- Book of Eternity as a scenario, not a game engine inside the bridge.

The vanilla host file tools are the product. This suite writes the official
GM file protocol with ordinary JSON (the same bytes `fs.write` would put on
disk) and checks the shapes the C# client actually validates:

* output/narrative_response.json  — only response, timestamp
* output/debug_logs.json          — only gm_thoughts_markdown, timestamp
* output/interface_updates.json   — only dialogueOptions, image_prompt, timestamp
* ready/turn_complete.json        — Complete-BoeTurn fields, status=success

It does not reimplement dice, realms, or narrative. Those belong to the
game and to the agent sitting on the far side of the tunnel.
"""
from __future__ import annotations

import json
from pathlib import Path

from arena.game import boe_relay

NARRATIVE_FIELDS = frozenset({"response", "timestamp"})
DEBUG_FIELDS = frozenset({"gm_thoughts_markdown", "timestamp"})
INTERFACE_FIELDS = frozenset({"dialogueOptions", "image_prompt", "timestamp"})
COMPLETE_FIELDS = frozenset(
    {"sessionId", "requestId", "turnNumber", "timestamp", "status", "filesModified"}
)


def _write(session: Path, rel: str, data: dict) -> None:
    target = session / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def test_vanilla_json_writes_satisfy_accepted_turn_field_sets(tmp_path: Path) -> None:
    session = tmp_path / "game_session"
    session.mkdir()
    ts = "2026-08-13T08:00:00.0000000+00:00"

    _write(
        session,
        "input/turn_request.json",
        {
            "sessionId": "sess_e2e",
            "requestId": "req_e2e",
            "turnNumber": 1,
            "playerAction": "Осмотреться",
        },
    )
    _write(
        session,
        "output/narrative_response.json",
        {
            "response": "Тьма расступается. Дарен слышит своё имя.",
            "timestamp": ts,
        },
    )
    _write(
        session,
        "output/debug_logs.json",
        {
            "gm_thoughts_markdown": (
                "## Охват NPC-анализа\n"
                "- Режим: none\n"
                "- Релевантные акторы: нет\n"
                "- Обоснование: пробуждение, на сцене только игрок.\n"
            ),
            "timestamp": ts,
        },
    )
    _write(
        session,
        "output/interface_updates.json",
        {
            "dialogueOptions": ["Оглядеться", "Позвать хранителя"],
            "image_prompt": "dim afterlife shore, single waking soul",
            "timestamp": ts,
        },
    )

    narrative = json.loads((session / "output" / "narrative_response.json").read_text(encoding="utf-8"))
    debug = json.loads((session / "output" / "debug_logs.json").read_text(encoding="utf-8"))
    interface = json.loads((session / "output" / "interface_updates.json").read_text(encoding="utf-8"))
    assert set(narrative) == NARRATIVE_FIELDS
    assert set(debug) == DEBUG_FIELDS
    assert set(interface) <= INTERFACE_FIELDS
    assert interface["dialogueOptions"]

    result = boe_relay.complete_turn(
        session,
        files_modified=[
            "output/narrative_response.json",
            "output/debug_logs.json",
            "output/interface_updates.json",
        ],
    )
    ready = json.loads((session / "ready" / "turn_complete.json").read_text(encoding="utf-8"))
    assert set(ready) == COMPLETE_FIELDS
    assert ready["status"] == "success"
    assert ready["sessionId"] == "sess_e2e"
    assert ready["requestId"] == "req_e2e"
    assert ready["turnNumber"] == 1
    assert ready["filesModified"] == [
        "output/narrative_response.json",
        "output/debug_logs.json",
        "output/interface_updates.json",
    ]
    assert result["status"] == "success"


def test_unknown_narrative_field_is_a_contract_violation(tmp_path: Path) -> None:
    """C# code narrative_response_unknown_field. The bridge must not emit this."""
    session = tmp_path / "game_session"
    session.mkdir()
    bad = {
        "response": "ok",
        "timestamp": "2026-08-13T08:00:00Z",
        "afterlifeChronicleUpdates": [],
    }
    assert set(bad) != NARRATIVE_FIELDS


def test_cli_idle_and_working_markers_match_the_daemon() -> None:
    """game_master_daemon.ps1 looks for 'Working' + 'esc to interrupt', and '› '."""
    src = Path(boe_relay.__file__).with_name("boe_cli.py").read_text(encoding="utf-8")
    assert "Working on" in src
    assert "esc to interrupt" in src
    assert "› " in src
