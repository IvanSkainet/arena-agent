"""Chat extension adapter flow regressions."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_chat_extension_adapter_helpers_exist():
    adapters = (ROOT / 'chat_extension' / 'adapters.js').read_text(encoding='utf-8')
    adapter_sites = (ROOT / 'chat_extension' / 'adapter_sites.js').read_text(encoding='utf-8')
    parser = (ROOT / 'chat_extension' / 'parser.js').read_text(encoding='utf-8')
    content = (ROOT / 'chat_extension' / 'content.js').read_text(encoding='utf-8')
    settings = (ROOT / 'chat_extension' / 'settings.js').read_text(encoding='utf-8')
    assert 'arenaHasArenaToolBlock' in adapters
    assert 'arenaHasToolBlock' in adapters
    assert 'function_call_start' in adapters
    assert 'arenaIsAssistantNode' in adapters
    assert 'arenaMessageFingerprint' in adapters
    assert 'arenaLatestCandidateNodes' in adapters
    assert 'arenaExtractNodeId' in adapters
    assert 'arenaCandidateHost' in adapters
    assert 'arenaPruneAncestorCandidates' in adapters
    assert 'arenaNodePath' in adapters
    assert 'chatgpt.com' in adapter_sites
    assert 'gemini.google.com' in adapter_sites
    assert 'claude.ai' in adapter_sites
    assert "messageSelectors: ['[data-test-render-count]']" in adapter_sites
    assert 'requestIdleCallback' in content
    assert 'arenaHasComposerChild' in adapters
    assert 'arenaSelectorDiagnostics' in adapters
    assert 'selector_hits' in content
    assert 'user-message' in adapters
    assert "startsWith('You said:')" in adapters
    assert 'grok.com' in adapter_sites
    assert 'openrouter.ai' in adapter_sites
    assert 'chat.deepseek.com' in adapter_sites
    assert 'chat.qwen.ai' in adapter_sites
    assert 'arenaPayloadFromJsonl' in parser
    assert 'sys.status' in (ROOT / 'arena' / 'extension_bridge' / 'instructions.py').read_text(encoding='utf-8')
    assert 'sys.status' in (ROOT / 'arena' / 'extension_bridge' / 'policy.py').read_text(encoding='utf-8')
    assert "kind: 'jsonl-inline'" in parser
    assert "text.includes('function_call_start')" in adapters
    assert "'pre'" in adapter_sites
    assert "'code'" in adapter_sites
    assert "[class*=\\\"code\\\"]" in adapter_sites
    assert 'arenaInsertAndSubmit' in adapters
    assert 'Send' in content
    assert 'scheduleScan' in content
    assert 'scanPageDiagnostics' in content
    assert 'candidate_nodes' in content
    assert 'parsed_blocks' in content
    assert 'data-arena-tool-controls' in content
    assert 'arenaToolControlsMounted' in content
    assert 'insertAdjacentElement' in content
    assert 'MutationObserver' in content
    assert 'runAutoModes' in content
    assert 'autoExecuteSafe' in settings
    assert 'autoSubmitResult' in settings
    assert 'insertStrategy' in settings
    assert 'async function arenaInsertAndSubmit' in adapters
    assert 'arenaInsertIntoEditable' in adapters
    assert 'arenaFocusComposer' in adapters
    assert 'arenaSetInsertTiming' in adapters
    assert '__arenaLastInsertTiming' in adapters
    assert 'arenaNormalizeInsertStrategy' in adapters
    assert 'arenaPasteOnly' in adapters
    assert 'arenaDirectDomText' in adapters
    assert 'directDomText' in adapters
    assert 'paragraphFallback' in adapters
    assert "insertText" in adapters
    assert "insertParagraph" in adapters
    assert 'setTimeout' in adapters

    assert 'arenaDetectionText' in adapters
    assert 'arenaIsComposerNode' in adapters
    assert 'arenaMatchesAny' in adapters
    assert 'previewSummary' in content
    assert 'dismissed_controls' in content
    assert 'arenaSplitJsonObjects' in parser
    assert 'arena.showPageControls' in content
    assert 'formatInsertText' in content
    assert 'pointerdown' in content and 'preventDefault' in content
    assert 'Inserted/submitted' in content
    assert 'timingSummary' in content
    assert 'currentInsertStrategy' in content
    assert 'suppressCurrentControls' in content
    assert 'dismissedControls' in content


def test_chat_extension_readme_tracks_scaffold_version_and_features():
    readme = (ROOT / 'chat_extension' / 'README.md').read_text(encoding='utf-8')
    assert 'Current scaffold extension version: `0.12.1`.' in readme
    assert 'Insert & Submit' in readme or 'Send' in readme
    assert 'side panel UI' in readme
