"""The legacy remember command and helper API serialize the same journal."""
from __future__ import annotations

import concurrent.futures
import json

from arena.agent_helpers import runtime
from arena.agentctl_extras import actions


def test_mixed_fact_writers_preserve_all_records_and_separate_torn_tail(tmp_path, monkeypatch):
    facts = tmp_path / "memory" / "facts.jsonl"
    facts.parent.mkdir()
    facts.write_bytes(b'{"unfinished":')
    monkeypatch.setattr(runtime, "FACTS", facts)
    monkeypatch.setattr(actions, "ROOT", tmp_path)

    def write(index):
        key = f"mixed-{index}"
        if index % 2:
            assert actions.cmd_remember([key, "legacy value"]) == 0
        else:
            runtime.put_fact(key, "helper value")

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(write, range(32)))
    lines = facts.read_text().splitlines()
    assert lines[0] == '{"unfinished":'
    records = [json.loads(line) for line in lines[1:]]
    assert len(records) == 32
    assert {record["key"] for record in records} == {f"mixed-{i}" for i in range(32)}
    assert sum(record.get("val") == "legacy value" for record in records) == 16
    assert sum(record.get("value") == "helper value" for record in records) == 16
