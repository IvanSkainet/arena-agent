"""v4.35.0: close the last dashboard-tab scoping gap.

Live (body-17-live.html) and ZeroTier (body-18-zerotier.html)
carried legacy <style> blocks whose selectors were unscoped
(``.live-*`` / ``.ztc-*``). In practice the prefixes were
unique so no leakage happened, but they bypassed the v4.0.x
lesson enforcement that every other tab in the redesign arc
respects. This release scopes every selector to the tab id.

Same test shape as ``test_seven_tabs_redesign.py`` / other
scoped-CSS enforcement.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest


_REPO = Path(__file__).resolve().parents[1]
_ASSETS = _REPO / "dashboard" / "assets"


TAB_SPECS = [
    ("body-17-live.html", "tab-live"),
    ("body-18-zerotier.html", "tab-zerotier"),
]


def _read(name: str) -> str:
    return (_ASSETS / name).read_text(encoding="utf-8")


def _strip_comments(css: str) -> str:
    return re.sub(r"/\*.*?\*/", "", css, flags=re.DOTALL)


def _iter_selectors(css: str):
    """Yield each top-level selector (comma-split, whitespace-
    stripped) from ``css``. Strips comments first, then walks."""
    css = _strip_comments(css)
    i, n = 0, len(css)
    while i < n:
        if css[i] == "@":
            open_b = css.find("{", i)
            if open_b == -1:
                return
            depth = 1
            j = open_b + 1
            while j < n and depth > 0:
                if css[j] == "{":
                    depth += 1
                elif css[j] == "}":
                    depth -= 1
                j += 1
            i = j
            continue
        open_b = css.find("{", i)
        if open_b == -1:
            return
        selector_block = css[i:open_b].strip()
        depth = 1
        j = open_b + 1
        while j < n and depth > 0:
            if css[j] == "{":
                depth += 1
            elif css[j] == "}":
                depth -= 1
            j += 1
        i = j
        if not selector_block:
            continue
        for part in selector_block.split(","):
            p = part.strip()
            if p and not p.startswith("@"):
                yield p


@pytest.mark.parametrize("body_name,tab_id", TAB_SPECS)
def test_every_selector_scoped_to_tab_id(body_name, tab_id):
    body = _read(body_name)
    style_blocks = re.findall(r"<style>(.*?)</style>", body, flags=re.DOTALL)
    assert style_blocks, f"{body_name} has no <style> block"

    scope_prefix = f"#{tab_id}"
    unscoped = []
    for block in style_blocks:
        for sel in _iter_selectors(block):
            if not sel.startswith(scope_prefix):
                unscoped.append(sel)
    assert not unscoped, (
        f"{body_name} still has unscoped selectors after v4.35.0 "
        f"refactor:\n" + "\n".join(f"  {s}" for s in unscoped)
    )


@pytest.mark.parametrize("body_name,tab_id", TAB_SPECS)
def test_tab_wrapper_id_still_present(body_name, tab_id):
    body = _read(body_name)
    assert f'id="{tab_id}"' in body


def test_live_preserves_all_ids():
    body = _read("body-17-live.html")
    critical_ids = [
        "liveStatus",
        "liveCpuValue", "liveCpuChart", "liveCpuMeta", "liveCpuPerCore",
        "liveMemValue", "liveMemChart", "liveMemMeta",
        "liveSwapValue", "liveSwapChart", "liveSwapMeta",
        "liveNetRxValue", "liveNetRxChart",
        "liveNetTxValue", "liveNetTxChart", "liveNetMeta",
    ]
    for id_ in critical_ids:
        assert f'id="{id_}"' in body, (
            f"Live redesign dropped #{id_} -- would silently break "
            f"the live-metrics loaders."
        )


def test_zerotier_preserves_all_ids():
    body = _read("body-18-zerotier.html")
    for id_ in ("ztcStatus",):
        assert f'id="{id_}"' in body


def test_live_preserves_class_names():
    """The <div>-side class names are what the JS reads to hydrate
    each sparkline. Missing any would break v4.0.x-scope enforcement
    silently (rules would target nothing)."""
    body = _read("body-17-live.html")
    for cls in (".live-grid", ".live-card", ".live-header",
                ".live-label", ".live-value", ".live-canvas",
                ".live-meta", ".live-dot", ".live-controls",
                ".livecore", ".livecore-label", ".livecore-bar",
                ".livecore-fill", ".livecore-val",
                ".live-status-text", ".live-hint"):
        assert cls in body, f"{cls} rule missing"


def test_zerotier_preserves_class_names():
    body = _read("body-18-zerotier.html")
    for cls in (".ztc-status-bar", ".ztc-create-row",
                ".ztc-net-row", ".ztc-members-panel"):
        assert cls in body


def test_no_bare_dot_live_selector_outside_tab():
    """Regression guard: no ``.live-*`` rule should be present in
    the Live style block without a ``#tab-live`` prefix. Same
    thing the parameterized test proves, but with an explicit
    grep-style assertion for future readers."""
    body = _read("body-17-live.html")
    style_blocks = re.findall(r"<style>(.*?)</style>", body, flags=re.DOTALL)
    for block in style_blocks:
        # Any line that starts with .live- (post-indent) is unscoped.
        for lineno, line in enumerate(block.splitlines(), 1):
            stripped = line.lstrip()
            if stripped.startswith((".live-", ".livecore")):
                pytest.fail(
                    f"body-17-live.html:{lineno} still has an unscoped "
                    f"selector: {stripped!r}"
                )


def test_no_bare_dot_ztc_selector_outside_tab():
    body = _read("body-18-zerotier.html")
    style_blocks = re.findall(r"<style>(.*?)</style>", body, flags=re.DOTALL)
    for block in style_blocks:
        for lineno, line in enumerate(block.splitlines(), 1):
            stripped = line.lstrip()
            if stripped.startswith(".ztc-"):
                pytest.fail(
                    f"body-18-zerotier.html:{lineno} still has an unscoped "
                    f"selector: {stripped!r}"
                )
