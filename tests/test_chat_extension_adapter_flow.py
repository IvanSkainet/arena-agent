"""Chat extension adapter flow regressions."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_chat_extension_adapter_helpers_exist():
    adapters = (ROOT / 'chat_extension' / 'adapters.js').read_text(encoding='utf-8')
    insert_strategies = (ROOT / 'chat_extension' / 'insert_strategies.js').read_text(encoding='utf-8')
    adapter_sites = (ROOT / 'chat_extension' / 'adapter_sites.js').read_text(encoding='utf-8')
    parser = (ROOT / 'chat_extension' / 'parser.js').read_text(encoding='utf-8')
    content = (ROOT / 'chat_extension' / 'content.js').read_text(encoding='utf-8')
    settings = (ROOT / 'chat_extension' / 'settings.js').read_text(encoding='utf-8')
    assert 'arenaHasArenaToolBlock' in adapters
    assert 'arenaHasToolBlock' in adapters
    assert 'function_call_start' in adapters
    assert 'arenaIsAssistantNode' in adapters
    assert 'arenaMessageFingerprint' in adapters
    assert 'arenaPayloadFingerprint' in adapters
    assert 'arenaPayloadSemanticFingerprint' in adapters
    assert 'arenaLatestCandidateNodes' in adapters
    assert 'arenaExtractNodeId' in adapters
    assert 'arenaCandidateHost' in adapters
    assert 'arenaPruneAncestorCandidates' in adapters
    assert 'arenaNodePath' in adapters
    assert 'arenaElementVisible' in adapters
    assert 'arenaResolveComposerNode' in adapters
    assert 'arenaComposerCandidates' in adapters
    assert 'arenaComposerSelection' in adapters
    assert 'arenaSubmitCandidates' in adapters
    assert 'arenaSubmitButtonSelection' in adapters
    assert 'chatgpt.com' in adapter_sites
    assert 'button[type="submit"]' in adapter_sites
    assert 'Отправ' in adapter_sites
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
    assert 't3.chat' in adapter_sites
    assert 'chat.z.ai' in adapter_sites
    assert '[class*="message"]' in adapter_sites
    assert '[class*="markdown"]' in adapter_sites
    assert 'arenaPayloadFromJsonl' in parser
    assert 'arenaLooksLikeBridgeInstructions' in parser
    assert 'sys.status' in (ROOT / 'arena' / 'extension_bridge' / 'instructions.py').read_text(encoding='utf-8')
    assert 'sys.status' in (ROOT / 'arena' / 'extension_bridge' / 'policy.py').read_text(encoding='utf-8')
    assert "kind: 'jsonl-inline'" in parser
    assert "text.includes('function_call_start')" in adapters
    assert "'pre'" in adapter_sites
    assert "'code'" in adapter_sites
    assert "[class*=\\\"code\\\"]" in adapter_sites
    assert 'arenaInsertAndSubmit' in insert_strategies
    assert 'Send' in content
    assert 'scheduleScan' in content
    assert 'scanPageDiagnostics' in content
    assert 'content_version' in content
    assert 'composer' in content
    assert 'candidate_nodes' in content
    assert 'parsed_blocks' in content
    assert 'diagnostic_summary' in content
    assert 'semantic_unique_blocks' in content
    assert 'semantic_duplicate_blocks' in content
    assert 'data-arena-tool-controls' in content
    assert 'arenaToolControlsMounted' in content
    assert 'insertAdjacentElement' in content
    assert 'MutationObserver' in content
    assert 'runAutoModes' in content
    assert 'autoExecuteSafe' in settings
    assert 'autoSubmitResult' in settings
    assert 'insertStrategy' in settings
    assert 'async function arenaInsertAndSubmit' in insert_strategies
    assert 'arenaTryEditableInsert' in insert_strategies
    assert 'arenaFocusComposer' in insert_strategies
    assert 'arenaSetInsertTiming' in insert_strategies
    assert '__arenaLastInsertTiming' in insert_strategies
    assert 'arenaNormalizeInsertStrategy' in insert_strategies
    assert 'arenaPasteOnly' in insert_strategies
    assert 'arenaDirectDomText' in insert_strategies
    assert 'directDomText' in insert_strategies
    assert 'arenaDirectDomBlocks' in insert_strategies
    assert 'directDomBlocks' in insert_strategies
    assert 'arenaDirectDomPreWrap' in insert_strategies
    assert 'directDomPreWrap' in insert_strategies
    assert 'arenaVerifySettledInsert' in insert_strategies
    assert 'arenaInsertPlan' in insert_strategies
    assert 'arenaUsesRichTextareaFastPath' in insert_strategies
    assert 'arenaComposerDiagnostics' in insert_strategies
    assert 'composer_candidates' in insert_strategies
    assert 'composer_selector' in insert_strategies
    assert 'text_length' in insert_strategies
    assert 'has_text' in insert_strategies
    assert 'submit_candidates' in insert_strategies
    assert 'submit_selector' in insert_strategies
    assert 'submit_scope' in insert_strategies
    assert 'submit_scope_buttons' in insert_strategies
    assert 'submit_scope_visible_buttons' in insert_strategies
    assert 'submit_scope_samples' in insert_strategies
    assert 'submit_selected_sample' in insert_strategies
    assert 'submit_enabled' in insert_strategies
    assert 'arenaButtonDiagnosticSample' in insert_strategies
    assert 'submit_expected_after_text' in insert_strategies
    assert 'submit_phase' in insert_strategies
    assert 'submit_note' in insert_strategies
    assert 'arenaInsertScriptVersion' in insert_strategies
    assert "arenaHost() === 'gemini.google.com'" in insert_strategies
    assert "closest?.('rich-textarea')" in insert_strategies
    assert 'arenaCompactTextForVerify' in insert_strategies
    assert 'changed' in insert_strategies
    assert 'paragraphFallback' in insert_strategies
    assert "insertText" in insert_strategies
    assert "insertParagraph" in insert_strategies
    assert 'setTimeout' in insert_strategies

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
    assert 'Auto used' in content
    assert 'attemptsSummary' in content
    assert 'currentInsertStrategy' in content
    assert 'suppressCurrentControls' in content
    assert 'dismissedControls' in content
    assert 'mountedPayloadSemantics' in content
    assert 'mountedSemanticOwners' in content
    assert 'executionResults' in content
    assert 'detectedPayloads' in content
    assert 'payload_instance_fingerprint' in content
    assert 'payload_fingerprint' in content


def test_chat_extension_readme_tracks_scaffold_version_and_features():
    readme = (ROOT / 'chat_extension' / 'README.md').read_text(encoding='utf-8')
    # v4.48.4 continues the extension polish arc; version banner
    # follows the release.
    assert 'Current extension version: `0.14.34`' in readme
    assert 'chrome.storage.local' in readme
    assert 'device-local' in readme
    assert '127.0.0.1:8765' in readme
    assert 'Insert & Submit' in readme or 'Send' in readme
    assert 'side panel UI' in readme

