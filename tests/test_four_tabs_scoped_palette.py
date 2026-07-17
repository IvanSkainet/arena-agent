"""v4.31.0 batch: add scoped <style> block with palette + helper
classes to four larger tabs -- Workspace, Doctor, Control,
Settings. Same incremental approach as Mobile v4.29.0: preserve
every existing id and inline style, just add a scoped palette
declaration at the top so future patches can migrate individual
sections onto the shared helper classes."""
from __future__ import annotations

import re
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[1]
_ASSETS = _REPO / "dashboard" / "assets"


# (body file, tab id, palette-prefix, critical ids that must survive,
#  helper classes that must appear)
TAB_SPECS = [
    ("body-01b-workspace.html", "tab-workspace", "ws", [
        "workspaceGoal", "workspaceContext", "workspaceConstraints",
        "workspaceMissionId", "workspaceMissionRun",
        "workspacePlanResult", "workspaceReactResult",
        "workspaceLessons", "workspaceLessonText",
        "workspaceMissionCatalog", "workspaceMissionSchedules",
        "watchPath", "watchLabel", "workspaceActivity",
    ], [".ws-toolbar", ".ws-meta", ".ws-hint", ".ws-section-badge"]),
    ("body-12-doctor.html", "tab-doctor", "dc", [
        "doctorResults", "doctorRemoteAccess", "doctorTailscale",
        "serviceStatus", "hwCards", "hwGeneratedAt", "hwRawJson",
    ], [".dc-toolbar", ".dc-meta", ".dc-hint", ".dc-section-badge"]),
    ("body-14-control.html", "tab-control", "ct", [
        "controlBigLabel", "controlBigReason", "controlBigStatus",
        "ctrlPauseBtn", "ctrlResumeBtn", "ctrlRevokeBtn",
        "ctrlStatusBadge", "ctrlWinTitle", "ctrlWinPid",
        "ctrlSession", "guardTestResult", "guardTitleInput",
    ], [".ct-toolbar", ".ct-meta", ".ct-hint", ".ct-section-badge"]),
    ("body-15-settings.html", "tab-settings", "st", [
        "setVersion", "setUptime", "setRequests", "setErrors",
        "setToken", "setWebhookUrls", "setWebhookEvents",
        "setServiceMode", "envInfo",
        "agentsBadge", "agentsTableBody", "agentsNewId",
        "agentsNewToken", "agentsNewTokenBox",
        "adminUpdateBadge", "adminUpdateStatus",
        "adminUpdateInstallBtn", "adminUpdateDetails",
        "adminUpdateReleaseBody",
    ], [".st-toolbar", ".st-meta", ".st-hint", ".st-section-badge"]),
]


def _read(body_name):
    return (_ASSETS / body_name).read_text(encoding="utf-8")


@pytest.mark.parametrize("body_name,tab_id,prefix,critical_ids,helpers", TAB_SPECS)
def test_scoped_style_block_added(body_name, tab_id, prefix, critical_ids, helpers):
    body = _read(body_name)
    style_blocks = re.findall(r"<style>(.*?)</style>", body,
                              flags=re.DOTALL)
    assert len(style_blocks) >= 1


@pytest.mark.parametrize("body_name,tab_id,prefix,critical_ids,helpers", TAB_SPECS)
def test_every_selector_scoped(body_name, tab_id, prefix, critical_ids, helpers):
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
                    f"{body_name}: unscoped selector {sel!r}"
                )


@pytest.mark.parametrize("body_name,tab_id,prefix,critical_ids,helpers", TAB_SPECS)
def test_palette_var_declared_inside_tab(body_name, tab_id, prefix, critical_ids, helpers):
    body = _read(body_name)
    assert f"#{tab_id}{{" in body or f"#{tab_id} {{" in body
    for suffix in ("green", "blue", "red", "gray"):
        assert f"--{prefix}-tint-{suffix}" in body


@pytest.mark.parametrize("body_name,tab_id,prefix,critical_ids,helpers", TAB_SPECS)
def test_all_helper_classes_declared(body_name, tab_id, prefix, critical_ids, helpers):
    body = _read(body_name)
    for cls in helpers:
        assert cls in body, f"{body_name} missing helper class {cls}"


@pytest.mark.parametrize("body_name,tab_id,prefix,critical_ids,helpers", TAB_SPECS)
def test_critical_ids_preserved(body_name, tab_id, prefix, critical_ids, helpers):
    body = _read(body_name)
    for id_ in critical_ids:
        assert f'id="{id_}"' in body, (
            f"{body_name} dropped critical id #{id_}"
        )
