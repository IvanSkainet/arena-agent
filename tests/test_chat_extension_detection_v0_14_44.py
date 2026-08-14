"""v0.14.44: candidate discovery must accept every parser-owned call shape.

The live arena.ai UI exposed a split grammar: ``parser.js`` accepted the
canonical ``bridge=arena`` envelope, while ``adapters.js`` filtered candidates
unless their text contained a JSONL ``function_call_start``/``arena_tool``
marker. The block was valid but could never receive Run controls.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tests._node_budget import node_timeout  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
EXT = ROOT / "chat_extension"


def _have_node() -> bool:
    return shutil.which("node") is not None


def _detect(text: str) -> bool:
    parser = (EXT / "parser.js").read_text(encoding="utf-8")
    adapters = (EXT / "adapters.js").read_text(encoding="utf-8")
    script = (
        "const location={hostname:'arena.ai',pathname:'/c/live'};"
        "const document={querySelectorAll:()=>[],querySelector:()=>null};"
        "const window={};"
        + parser
        + "\n"
        + adapters
        + "\n"
        + f"arenaDetectionText=()=>{json.dumps(text)};"
        + "process.stdout.write(String(arenaHasToolBlock({}, {})));"
    )
    # Feed the harness over stdin. Passing parser.js + adapters.js through
    # ``node -e`` exceeds Windows' process command-line limit (WinError 206),
    # even though the same test is small and fast once Node starts.
    result = subprocess.run(
        ["node", "-"],
        input=script,
        capture_output=True,
        text=True,
        timeout=node_timeout(),
        check=False,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout.strip() == "true"


@pytest.mark.skipif(not _have_node(), reason="node.js required")
@pytest.mark.parametrize(
    "block",
    [
        """```arena-tool
{"bridge":"arena","version":1,"calls":[{"id":"ui","tool":"relay.status","arguments":{}}]}
```""",
        '{"bridge":"arena","version":1,"calls":[{"id":"ui","tool":"relay.status","arguments":{}}]}',
        """```json
{"tool":"relay.status","arguments":{}}
```""",
        """```jsonl
{"type":"function_call_start","call_id":"ui","name":"relay.status"}
{"type":"function_call_end"}
```""",
    ],
)
def test_candidate_detection_accepts_every_parser_owned_shape(block: str) -> None:
    assert _detect(block)


@pytest.mark.skipif(not _have_node(), reason="node.js required")
@pytest.mark.parametrize(
    "text",
    [
        "ordinary assistant prose without a call",
        "```json\n{\"bridge\":\"other\",\"calls\":[]}\n```",
        (
            "You are connected to a local Arena Chat Bridge that can execute tools.\n"
            "```arena-tool\n"
            '{"bridge":"arena","version":1,"calls":[{"id":"doc","tool":"relay.status","arguments":{}}]}\n'
            "```"
        ),
    ],
)
def test_candidate_detection_keeps_parser_false_positive_guards(text: str) -> None:
    assert not _detect(text)


def test_adapters_delegate_candidate_grammar_to_parser() -> None:
    adapters = (EXT / "adapters.js").read_text(encoding="utf-8")
    assert "parseArenaBlocks(text).length > 0" in adapters
    assert "const ARENA_TOOL_RE" not in adapters
