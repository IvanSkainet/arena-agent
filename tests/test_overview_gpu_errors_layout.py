"""Static structural checks for the Overview GPU + errors cards.

The cards are optional -- when the host has no GPU or no
systemd, the JS hides the section entirely. But the HTML
elements must exist so the loader has somewhere to write.
These tests guarantee the elements + the scoped styles + the
JS module hygiene.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[1]
_BODY = _REPO / "dashboard" / "assets" / "body-01-overview.html"
_JS = _REPO / "dashboard" / "assets" / "04e-overview-gpu-errors.js"


@pytest.fixture(scope="module")
def body_html() -> str:
    return _BODY.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def js_text() -> str:
    return _JS.read_text(encoding="utf-8")


GPU_IDS = [
    "gpuCard", "gpuBadge", "gpuEmpty", "gpuBody",
    "gpuName", "gpuDriver",
    "gpuUtilBar", "gpuUtilText",
    "gpuVramBar", "gpuVramText",
    "gpuTempText",
]

ERR_IDS = [
    "errCard", "errBadge", "errEmpty", "errBody",
    "errSystemCount", "errUserCount", "errList",
]


@pytest.mark.parametrize("id_", GPU_IDS + ERR_IDS)
def test_required_id_present(body_html: str, id_: str):
    assert f'id="{id_}"' in body_html, f"missing #{id_} in Overview body"


def test_gpu_and_error_h2s_present(body_html: str):
    assert "<h2>GPU" in body_html
    assert "<h2>Recent System Errors" in body_html


def test_new_scoped_css_rules_target_gpu_and_err_ids(body_html: str):
    """Every new CSS rule must be under #tab-overview (v4.0.x
    lesson) AND target one of the new ids so the shared sheet
    stays untouched."""
    assert "#tab-overview #gpuCard" in body_html
    assert "#tab-overview #errCard" in body_html
    assert "#tab-overview #errList" in body_html
    assert "#tab-overview #gpuBadge" in body_html
    assert "#tab-overview #errBadge" in body_html


def test_progress_bars_reuse_existing_shared_classes(body_html: str):
    """.progress-bar / .fill / .text come from the shared sheet.
    We reuse them for GPU utilization + VRAM so the visuals stay
    consistent with CPU/RAM/Disk. No local reimplementation."""
    # Sanity: both progress bar ids show up in a progress-bar wrapper.
    assert 'id="gpuUtilBar"' in body_html
    assert 'id="gpuVramBar"' in body_html
    # Neighborhood check: within ~200 chars of gpuUtilBar we should see
    # class="fill green" (util). Same for gpuVramBar and fill blue.
    for anchor, expected_fill in (
        ("gpuUtilBar", "fill green"),
        ("gpuVramBar", "fill blue"),
    ):
        idx = body_html.find(anchor)
        assert idx != -1, f"missing {anchor}"
        window = body_html[max(0, idx - 200):idx + 200]
        assert "progress-bar" in window, (
            f"{anchor} is not inside a progress-bar container"
        )
        assert expected_fill in window, (
            f"{anchor} not paired with {expected_fill!r} within 200 chars"
        )


# ---------------------------------------------------------------------------
# JS module hygiene
# ---------------------------------------------------------------------------
def test_js_is_iife_and_wraps_refreshOverview(js_text: str):
    lines = [l.strip() for l in js_text.splitlines()
             if l.strip() and not l.strip().startswith("//")]
    assert lines[0].startswith("(function"), "module must be an IIFE"
    assert "window.refreshOverview" in js_text
    assert "_origRefresh" in js_text


def test_js_exposes_diagnostic_namespace(js_text: str):
    assert "__overviewGpuErrors" in js_text
    assert "enumerable: false" in js_text


def test_js_uses_existing_api_helper_when_available(js_text: str):
    """The other Overview loaders use window.api() so bearer auth
    is uniform. Our module falls back to fetch() only when api()
    isn't present."""
    assert "window.api" in js_text
    assert 'fetch("/v1/hwinfo"' in js_text


def test_js_never_hides_via_shared_class(js_text: str):
    """Hiding uses `style.display = "none"` (per-element) rather
    than adding a shared '.hidden' class. That keeps display
    control local to the tab -- same discipline the toolbar
    wrapper uses."""
    assert 'classList.add("hidden")' not in js_text


def test_js_only_targets_gpu_and_err_ids(js_text: str):
    """The module must not reach into any id outside its own scope
    -- otherwise it starts to look like the third overlapping
    Overview loader. Whitelist the ids it may query."""
    allowed = set(GPU_IDS + ERR_IDS)
    reached = set(re.findall(r'_q\("([a-zA-Z][a-zA-Z0-9_]*)"\)', js_text))
    stray = reached - allowed
    assert stray == set(), (
        f"module reads unknown ids: {sorted(stray)}. Restrict to "
        f"the gpu/err card ids so responsibility stays clear."
    )


def test_js_prefix_places_after_toolbar_module(js_text: str):
    """04e- prefix loads AFTER 04d-overview-toolbar.js so we wrap
    an already-wrapped refreshOverview -- both wrappers stack."""
    assert _JS.name == "04e-overview-gpu-errors.js"
