"""Chat extension sidepanel flow regressions."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_sidepanel_supports_filters_and_payload_inspection():
    html = (ROOT / 'chat_extension' / 'sidepanel.html').read_text(encoding='utf-8')
    js = (ROOT / 'chat_extension' / 'sidepanel.js').read_text(encoding='utf-8')
    assert 'kindFilter' in html
    assert '<option value="scan">scan</option>' in html
    assert '<option value="insert">insert</option>' in html
    assert '<option value="submit">submit</option>' in html
    assert 'siteFilter' in html
    assert 'adapterFilter' in html
    assert 'applyFilterBtn' in html
    assert 'payloadBox' in html
    assert 'resultBox' in html
    assert 'renderPayload' in js
    assert 'renderResult' in js
    assert 'Copy Payload' in js
    assert 'Copy Result' in js
    css = (ROOT / 'chat_extension' / 'popup.css').read_text(encoding='utf-8')
    assert 'arena.getHistory' in js
    assert 'renderCardHeader' in js
    assert 'itemTools' in js
    assert 'itemStatus' in js
    assert 'scanDiagnostics' in js
    assert 'bridgeDiagnostics' in js
    assert 'versionDiagnostics' in js
    assert 'insertionDiagnostics' in js
    assert 'cardMetaParts' in js
    assert 'groupCommandHistory' in js
    assert 'commandGroupFromEvents' in js
    assert 'lifecycleKinds' in js
    assert 'lifecycleSummary' in js
    assert "'detected', 'preview', 'execute', 'insert', 'submit'" in js
    assert 'historyActionIndex' in js
    assert 'payloadSourceItem' in js
    assert 'resultSourceItem' in js
    assert 'finalResultItem' in js
    assert 'replaySourceItem' in js
    assert 'Inspect Final Result' in js
    assert 'scheduleFilterReload' in js
    assert "getElementById('kindFilter').addEventListener('change', loadHistory)" in js
    assert "auto: ${composer.auto_plan.join(' → ')}" in js
    assert 'submit after text' in js
    assert 'bridge fallback' in js
    assert 'shortUrl' in js
    assert 'arena-history-card' in css
    assert 'arena-badge' in css
    assert 'arena-badge-flow' in css


def test_background_supports_history_item_and_filters():
    bg = (ROOT / 'chat_extension' / 'background.js').read_text(encoding='utf-8')
    assert 'getHistory(filters = {})' in bg
    assert 'history_index: index' in bg
    assert 'getHistoryItem' in bg
    assert 'arena.getHistoryItem' in bg
    assert 'arena.insertEvent' in bg
    assert 'adapter: message.body?.site?.adapter' in bg
    assert 'response: compactResult(result)' in bg
    assert 'while fetching ${base}${path}' in bg
    assert 'bridge_url: base' in bg
    assert 'bridge_url_fallback' in bg
    assert 'bridgeFallbackBase' in bg
    assert 'bridgeFetchOnce' in bg
    assert 'chrome.storage.local.get({bridgeToken: ' in bg
    assert 'chrome.storage.local.set({bridgeToken})' in bg
    assert "chrome.storage.sync.remove('bridgeToken')" in bg
    assert 'HISTORY_AGGREGATE_MS' in bg
    assert 'historyAggregateKey' in bg
    assert 'isAggregatedHistoryKind' in bg
    assert "kind === 'scan'" in bg
    assert '×${count}' in bg
