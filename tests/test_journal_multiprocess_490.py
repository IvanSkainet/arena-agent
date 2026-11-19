"""Real competing processes must preserve each complete journal record."""
import json
import os
import subprocess
import sys
from pathlib import Path


def test_concurrent_fact_writers_preserve_torn_tail_and_all_records(tmp_path):
    journal = tmp_path / "facts.jsonl"
    journal.write_bytes(b'{"torn":')
    program = """
import sys
from pathlib import Path
from arena.agent_helpers import runtime
runtime.FACTS = Path(sys.argv[1])
for index in range(40):
    runtime.put_fact(f'{sys.argv[2]}-{index}', 'value-' + 'x' * 8192)
"""
    env = os.environ.copy()
    env["ARENA_AGENT_HOME"] = str(tmp_path / "home")
    processes = []
    try:
        for worker in range(4):
            processes.append(subprocess.Popen(
                [sys.executable, "-c", program, str(journal), str(worker)],
                cwd=Path(__file__).resolve().parents[1], env=env,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            ))
        for process in processes:
            stdout, stderr = process.communicate(timeout=60)
            assert process.returncode == 0, (stdout, stderr)
    finally:
        for process in processes:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=10)
    lines = journal.read_bytes().splitlines()
    assert lines[0] == b'{"torn":'
    records = [json.loads(line) for line in lines[1:]]
    assert len(records) == 160
    assert {record["key"] for record in records} == {
        f"{worker}-{index}" for worker in range(4) for index in range(40)
    }
    assert all(record["value"] == "value-" + "x" * 8192 for record in records)
