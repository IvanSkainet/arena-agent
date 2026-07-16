"""Static structural checks for the batched v4.30.0 redesign of
seven small tabs: Memory, Recall, Reports, Tasks, Skills, Hooks,
Agents.

Each of these tabs was under 30 lines of ad-hoc markup with no
scoped CSS at all. This redesign adds a scoped ``<style>`` block
per tab with palette + helpers, and preserves every id the JS
loaders depend on.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[1]
_ASSETS = _REPO / "dashboard" / "assets"


# Per-tab: (body file, tab id, list of critical ids that must survive)
TAB_SPECS = [
    ("body-03-memory.html", "tab-memory", [
        "memProfile", "memKey", "memValue", "memTags",
        "memSearch", "memoryTable", "memoryDigestPanel",
    ]),
    ("body-04-recall.html", "tab-recall", [
        "recallProfile", "recallQuery",
        "recallResults", "digestResults",
    ]),
    ("body-07-reports.html", "tab-reports", [
        "reportsTable", "reportPreview",
    ]),
    ("body-08-tasks.html", "tab-tasks", [
        "taskCountBadge", "taskSubmitPanel", "taskCmd",
        "taskTimeout", "taskCwd", "taskStats", "taskInbox",
        "taskRunning", "taskDone", "taskFailed", "tasksTable",
    ]),
    ("body-09-skills.html", "tab-skills", [
        "installSkillName", "installSkillUrl", "skillsTable",
        "skillDetail", "skillOutput", "skillOutputText",
    ]),
    ("body-10-hooks.html", "tab-hooks", ["hooksContainer"]),
    ("body-11-agents.html", "tab-agents", [
        "agentsTable", "agentDetail",
    ]),
]

# Per-tab: (body file, tab id, list of onclick handler names that
# must be wired). Guard against a redesign dropping a button.
HANDLER_SPECS = [
    ("body-03-memory.html", ["addMemory", "loadMemory",
                             "memoryDigest", "recallFromMemory"]),
    ("body-04-recall.html", ["runRecall", "memoryDigestFull"]),
    ("body-07-reports.html", ["loadReports"]),
    ("body-08-tasks.html", ["showTaskSubmit", "loadTasks",
                            "cleanTasks", "submitTask"]),
    ("body-09-skills.html", ["installSkill", "loadSkills"]),
    ("body-10-hooks.html", ["loadHooks"]),
    ("body-11-agents.html", ["loadAgents"]),
]


def _read(body_name: str) -> str:
    return (_ASSETS / body_name).read_text(encoding="utf-8")


@pytest.mark.parametrize("body_name,tab_id,critical_ids", TAB_SPECS)
def test_ids_preserved(body_name, tab_id, critical_ids):
    body = _read(body_name)
    assert f'id="{tab_id}"' in body
    for id_ in critical_ids:
        assert f'id="{id_}"' in body, (
            f"{body_name} redesign dropped #{id_}"
        )


@pytest.mark.parametrize("body_name,handlers", HANDLER_SPECS)
def test_handlers_wired(body_name, handlers):
    body = _read(body_name)
    for h in handlers:
        assert f"{h}()" in body, (
            f"{body_name} redesign dropped onclick handler {h}()"
        )


@pytest.mark.parametrize("body_name,tab_id,_", TAB_SPECS)
def test_scoped_style_block_added(body_name, tab_id, _):
    body = _read(body_name)
    style_blocks = re.findall(r"<style>(.*?)</style>", body,
                              flags=re.DOTALL)
    assert len(style_blocks) >= 1, (
        f"{body_name} must now carry at least one scoped <style> block"
    )


@pytest.mark.parametrize("body_name,tab_id,_", TAB_SPECS)
def test_every_selector_scoped(body_name, tab_id, _):
    body = _read(body_name)
    style_blocks = re.findall(r"<style>(.*?)</style>", body,
                              flags=re.DOTALL)

    def strip_comments(css):
        return re.sub(r"/\*.*?\*/", "", css, flags=re.DOTALL)

    def strip_at_rules(css):
        out, i = [], 0
        while i < len(css):
            if css[i] == "@":
                open_pos = css.find("{", i)
                if open_pos < 0:
                    break
                depth, j = 1, open_pos + 1
                while j < len(css) and depth > 0:
                    if css[j] == "{":
                        depth += 1
                    elif css[j] == "}":
                        depth -= 1
                    j += 1
                i = j
                continue
            out.append(css[i])
            i += 1
        return "".join(out)

    scope_prefix = f"#{tab_id}"
    for block in style_blocks:
        clean = strip_at_rules(strip_comments(block))
        for m in re.finditer(r"([^{}]+)\{[^{}]*\}", clean):
            for sel in m.group(1).split(","):
                sel = sel.strip()
                if not sel or sel.startswith("@"):
                    continue
                assert sel.startswith(scope_prefix), (
                    f"{body_name}: unscoped selector {sel!r} "
                    f"(must start with {scope_prefix})"
                )


@pytest.mark.parametrize("body_name,tab_id,_", TAB_SPECS)
def test_palette_var_declared_inside_tab(body_name, tab_id, _):
    body = _read(body_name)
    scope = f"#{tab_id}"
    assert scope + "{" in body or scope + " {" in body, (
        f"{body_name}: expected {scope}{{...}} palette declaration"
    )
