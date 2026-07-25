"""v4.89.0 — document.* deterministic structuring tools."""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from arena.document.structure import extract_tasks, structure_document, structure_physics_homework
from arena.extension_bridge.policy import classify_tool_risk
from arena.mcp.tool_document import handle_document_tool
from arena.mcp.tool_registry import MCP_TOOLS
from arena.mcp.tool_registry_document import DOCUMENT_MCP_TOOLS


def test_document_registry_and_policy():
    names = {t["name"] for t in DOCUMENT_MCP_TOOLS}
    assert names == {"document.extract_tasks", "document.structure"}
    assert names <= {t["name"] for t in MCP_TOOLS}
    assert classify_tool_risk("document.extract_tasks") == "safe"
    assert classify_tool_risk("document.structure") == "safe"


def test_extract_tasks_basic_ru():
    text = """TODO
- купить кофе завтра утром
- отправить отчёт вечером
проверить CI
"""
    out = extract_tasks(text, language="ru")
    assert out["ok"] is True
    assert out["count"] == 3
    assert out["tasks"][0]["title"] == "купить кофе завтра утром"
    assert out["tasks"][0]["due_text"] == "завтра утром"
    assert out["tasks"][1]["due_text"] == "вечером"


def test_extract_tasks_skips_short_formula_lines():
    out = extract_tasks("R = pL/S\n- решить задачу", language="ru")
    assert out["count"] == 1
    assert out["tasks"][0]["title"] == "решить задачу"


def test_structure_physics_homework_extracts_variables_and_formulas():
    text = """1. Дано: L1 = 0,2 м; L2 = 1,6 м; S1 = S2.
Найти: R2/R1?
Решение: R = ρL/S
Ответ: 8
"""
    out = structure_physics_homework(text)
    assert out["ok"] is True
    assert out["problem_count"] == 1
    p = out["problems"][0]
    assert p["number"] == "1"
    assert any(v["symbol"] == "L1" and v["value"] == 0.2 for v in p["given"])
    assert any("R =" in f for f in p["formulas"])
    assert p["find"]
    assert p["answer_lines"]


def test_structure_auto_chooses_tasks_then_physics():
    tasks = structure_document("- купить кофе\n- отправить отчёт", kind="auto")
    assert tasks["kind"] == "task_note"
    phys = structure_document("R = ρL/S\nL1 = 0.2 м", kind="auto")
    assert phys["kind"] == "physics_homework"


def test_handle_document_tool_wraps_content():
    out = handle_document_tool("document.extract_tasks", {"text": "- купить кофе"})
    assert out and "content" in out
    parsed = json.loads(out["content"][0]["text"])
    assert parsed["count"] == 1


def test_handle_document_tool_none_for_other():
    assert handle_document_tool("ocr.extract", {}) is None
