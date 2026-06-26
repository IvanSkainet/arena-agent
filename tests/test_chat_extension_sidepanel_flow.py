"""Chat extension sidepanel flow regressions."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_sidepanel_supports_filters_and_payload_inspection():
    html = (ROOT / 'chat_extension' / 'sidepanel.html').read_text(encoding='utf-8')
    js = (ROOT / 'chat_extension' / 'sidepanel.js').read_text(encoding='utf-8')
    assert 'kindFilter' in html
    assert 'siteFilter' in html
    assert 'applyFilterBtn' in html
    assert 'payloadBox' in html
    assert 'renderPayload' in js
    assert 'Copy Payload' in js
    assert 'arena.getHistory' in js


def test_background_supports_history_item_and_filters():
    bg = (ROOT / 'chat_extension' / 'background.js').read_text(encoding='utf-8')
    assert 'getHistory(filters = {})' in bg
    assert 'getHistoryItem' in bg
    assert 'arena.getHistoryItem' in bg
    assert 'site: message.body?.site?.origin' in bg
