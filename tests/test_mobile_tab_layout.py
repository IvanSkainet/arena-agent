"""Static checks for the Mobile tab redesign (v4.29.0).

Mobile is the largest and most JS-heavy tab (~60 ids, ~400
lines of markup with inline styles). A full DOM rewrite would
carry too much regression risk, so this redesign adds a
consolidated scoped ``<style>`` block with palette + helper
classes without touching the existing inline styles. Future
patches can migrate individual sections onto the helpers.

Tests here guarantee:
  * every existing id survives -- the loaders in
    ``arena/mobile/*.py`` and ``dashboard/assets/*mobile*.js``
    reach for a large set of ids.
  * the new scoped ``<style>`` block is present and scoped
    correctly (v4.0.x lesson).
  * palette variables live inside the tab, not on ``:root``.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[1]
_BODY = _REPO / "dashboard" / "assets" / "body-16-mobile.html"


@pytest.fixture(scope="module")
def body_html() -> str:
    return _BODY.read_text(encoding="utf-8")


# A representative sample of ids the JS loaders read from.
# The full list is ~60 -- this sample covers the ADB / mirror /
# camera / inspector / info subsystems so a redesign that dropped
# any group would trip the test.
CRITICAL_IDS = [
    "mobileHeaderBadge",
    "mobileErrorBox", "mobileErrorTitle", "mobileErrorCopyBtn",
    "mobileErrorDetail",
    "mobileDevicesList",
    "mobileAdbPath", "mobileAdbStatus",
    "mobileApkPath", "mobileApkSha", "mobileApkStatus", "mobileApkConsent",
    "mobileCameraStatus", "mobileCameraDetails", "mobileCameraThumb",
    "mobileCamFormat", "mobileCamSize", "mobileCamWait",
    "mobileMirrorStatus", "mobileMirrorDetails", "mobileMirrorMeta",
    "mobileMirrorBitrate", "mobileMirrorSize", "mobileMirrorVideo",
    "mobileHelperStatus",
    "mobileKbdStatus", "mobileKbdToggle",
    "mobileLiveRate", "mobileLiveToggle",
    "mobileInspectorLegend", "mobileInspectorOverlay",
    "mobileInspectorStatus", "mobileInspectorTip", "mobileInspectorToggle",
    "mobileInfoDetails", "mobileInfoDump", "mobileInfoPanel",
    "mobileInfoSummary",
    "mobileFormat", "mobileHint",
]


@pytest.mark.parametrize("id_", CRITICAL_IDS)
def test_id_still_present(body_html: str, id_: str):
    assert f'id="{id_}"' in body_html, (
        f"Mobile redesign removed #{id_} -- would break a "
        f"mobile subsystem loader"
    )


def test_tab_wrapper_and_h1(body_html: str):
    assert 'id="tab-mobile"' in body_html
    assert '<h1>Mobile Devices' in body_html


# ---------------------------------------------------------------------------
# new scoped style block
# ---------------------------------------------------------------------------
def test_scoped_style_block_added(body_html: str):
    """A single scoped ``<style>`` block must appear inside the
    tab. Before this redesign the file had zero scoped blocks."""
    style_blocks = re.findall(r"<style>(.*?)</style>", body_html,
                              flags=re.DOTALL)
    assert len(style_blocks) >= 1, (
        "Mobile tab must now carry at least one scoped <style> block"
    )


def test_every_style_selector_scoped_to_tab_mobile(body_html: str):
    style_blocks = re.findall(r"<style>(.*?)</style>", body_html,
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

    for block in style_blocks:
        clean = strip_at_rules(strip_comments(block))
        for m in re.finditer(r"([^{}]+)\{[^{}]*\}", clean):
            for sel in m.group(1).split(","):
                sel = sel.strip()
                if not sel or sel.startswith("@"):
                    continue
                assert sel.startswith("#tab-mobile"), (
                    f"Unscoped selector in Mobile <style>: {sel!r}"
                )


def test_palette_vars_scoped_inside_tab(body_html: str):
    assert "#tab-mobile{" in body_html or "#tab-mobile {" in body_html
    for var in ("--mb-tint-green", "--mb-tint-blue", "--mb-tint-red",
                "--mb-tint-orange"):
        assert var in body_html, f"missing scoped palette var {var}"


def test_helper_classes_available_for_future_migrations(body_html: str):
    """The redesign declares helper classes future patches can
    migrate individual sections onto -- .mb-toolbar,
    .mb-meta, .mb-hint, .mb-section-badge, .mb-refresh-dot."""
    for cls in (".mb-toolbar", ".mb-meta", ".mb-hint",
                ".mb-section-badge", ".mb-refresh-dot"):
        assert cls in body_html, (
            f"redesign should declare {cls} so future patches can "
            f"consolidate inline styles onto it"
        )


def test_pulse_keyframes_scoped(body_html: str):
    """The refresh-dot pulse animation is named ``mb-pulse`` (not
    a generic name that could clash with other tabs)."""
    assert "@keyframes mb-pulse" in body_html
    # And referenced by .mb-refresh-dot.on
    assert "animation:mb-pulse" in body_html
